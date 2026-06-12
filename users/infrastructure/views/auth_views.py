from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

import hashlib

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.conf import settings as django_settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from users.application.application.use_cases.user_usecases import CreateUserUseCase
from users.infrastructure.models import RolModel, UserModel
from users.infrastructure.repositories.user_repository_impl import UserRepositoryImpl
from users.infrastructure.views.auth_utils import post_login_redirect_url


class PasswordResetEmailView(auth_views.PasswordResetView):
    """Incluye `absolute_base` en el correo para que el enlace use el mismo host y puerto de la solicitud."""

    def form_valid(self, form):
        email = form.cleaned_data.get('email', '').strip().lower()
        exists = UserModel.objects.filter(email__iexact=email, activo=True).exists()
        if not exists:
            form.add_error('email', 'Este correo no está registrado.')
            return self.form_invalid(form)

        opts = {
            'use_https': self.request.is_secure(),
            'token_generator': self.token_generator,
            'from_email': self.from_email,
            'email_template_name': self.email_template_name,
            'subject_template_name': self.subject_template_name,
            'request': self.request,
            'html_email_template_name': self.html_email_template_name,
            'extra_email_context': {
                **(self.extra_email_context or {}),
                'absolute_base': self.request.build_absolute_uri('/').rstrip('/'),
            },
        }
        form.save(**opts)
        return HttpResponseRedirect(self.get_success_url())


def _safe_next_url(request):
    nxt = request.GET.get('next') or request.POST.get('next') or ''
    if not nxt:
        return None
    if url_has_allowed_host_and_scheme(
        nxt,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return nxt
    return None


def _client_ip(request):
    # Soporta proxies (si se configura X-Forwarded-For) y evita errores si no existe.
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _hash_key(val: str) -> str:
    return hashlib.sha256((val or '').encode('utf-8')).hexdigest()[:20]


def _enviar_correo_recuperacion_password(request, user):
    """
    Envía correo con link de restablecimiento de contraseña (token estándar de Django).
    Importante: no debe romper el login.
    """
    try:
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        absolute_base = request.build_absolute_uri('/').rstrip('/')
        html_message = render_to_string(
            'auth/password_reset_email.html',
            {
                'user': user,
                'uid': uidb64,
                'token': token,
                'absolute_base': absolute_base,
            },
            request=request,
        )

        subject = 'Restablecer contraseña — Olla y Sazón'
        msg = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', None),
            to=[user.email],
        )
        msg.content_subtype = 'html'
        # Para depurar en desarrollo: si falla el envío, mostramos el error en consola.
        msg.send(fail_silently=False)
    except Exception as exc:
        if getattr(django_settings, 'DEBUG', False):
            try:
                print('Error enviando correo de recuperación:', exc)
            except Exception:
                pass
        return


def login_view(request):
    if request.user.is_authenticated:
        return redirect(post_login_redirect_url(request.user))

    if request.method == 'POST':
        # Anti-bruteforce básico usando sesión (mejorable con cache/redis en producción).
        max_failed_attempts = 5
        lock_seconds = 10 * 60  # 10 minutos
        generic_error = 'Correo o contraseña incorrectos.'

        ip = _client_ip(request)
        ip_key = _hash_key(ip or 'no-ip')
        fail_key = f'login_fail_{ip_key}'
        lock_until_key = f'login_lock_until_{ip_key}'

        now_ts = int(timezone.now().timestamp())
        lock_until_ts = int(request.session.get(lock_until_key) or 0)
        if lock_until_ts and now_ts < lock_until_ts:
            messages.error(
                request,
                'Demasiados intentos fallidos. Intenta nuevamente más tarde.',
            )
            return render(
                request,
                'auth/login.html',
                {'form_errors': True, 'next': request.POST.get('next', '')},
                status=429,
            )

        # Soporta formularios que envíen el correo como `username` o como `email`.
        raw_email = (
            request.POST.get('username') or request.POST.get('email') or ''
        ).strip()
        email = raw_email.lower()
        password = (request.POST.get('password') or '').strip()

        # Validaciones de entrada.
        if not email or not password:
            messages.error(request, generic_error)
            return render(
                request,
                'auth/login.html',
                {'form_errors': True, 'next': request.POST.get('next', '')},
                status=400,
            )

        if len(raw_email) > 254 or len(password) > 128:
            messages.error(request, generic_error)
            return render(
                request,
                'auth/login.html',
                {'form_errors': True, 'next': request.POST.get('next', '')},
                status=400,
            )

        try:
            validate_email(email)
        except (ValidationError, ValueError):
            messages.error(request, generic_error)
            return render(
                request,
                'auth/login.html',
                {'form_errors': True, 'next': request.POST.get('next', '')},
                status=400,
            )

        # Django autentica contra `USERNAME_FIELD` que en tu User es el email.
        user = authenticate(request, username=email, password=password)
        if user and user.is_active:
            # Login exitoso: reiniciamos contadores.
            request.session.pop(fail_key, None)
            request.session.pop(lock_until_key, None)

            login(request, user)
            next_url = _safe_next_url(request)
            if next_url:
                return redirect(next_url)
            return redirect(post_login_redirect_url(user))

        # Fallo: incremento y posible lock. (Mensaje genérico para no enumerar usuarios)
        fail_count = int(request.session.get(fail_key) or 0) + 1
        request.session[fail_key] = fail_count
        if fail_count >= max_failed_attempts:
            request.session[lock_until_key] = now_ts + lock_seconds
            request.session[fail_key] = 0

            # Al bloquear por intentos fallidos: enviamos correo con link para restablecer contraseña.
            # Para evitar enumeración, solo enviamos si el usuario existe en BD.
            try:
                email_sent_key = f'login_lock_email_sent_{ip_key}'
                if not request.session.get(email_sent_key):
                    request.session[email_sent_key] = True
                    candidate = UserModel.objects.filter(email__iexact=email, activo=True).first()
                    if candidate and candidate.has_usable_password():
                        _enviar_correo_recuperacion_password(request, candidate)
            except Exception:
                pass

        messages.error(request, generic_error)
        return render(
            request,
            'auth/login.html',
            {'form_errors': True, 'next': request.POST.get('next', '')},
            status=400,
        )

    return render(request, 'auth/login.html', {'next': request.GET.get('next', '')})


@never_cache
def register_view(request):
    if request.user.is_authenticated:
        return redirect(post_login_redirect_url(request.user))

    rol_cliente = RolModel.objects.filter(nombre__iexact='CLIENTE').first()
    if not rol_cliente:
        messages.error(
            request,
            'No está configurado el rol CLIENTE en el sistema. Contacta al administrador.',
        )
        return redirect('login')

    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        apellido = (request.POST.get('apellido') or '').strip()
        email = (request.POST.get('email') or '').strip().lower()
        password = (request.POST.get('password') or '').strip()
        password2 = (request.POST.get('password2') or '').strip()

        posted = {'nombre': nombre, 'apellido': apellido, 'email': email}
        errors = []

        if not nombre or len(nombre) < 2:
            errors.append('El nombre debe tener al menos 2 caracteres.')
        elif any(c.isdigit() for c in nombre):
            errors.append('El nombre no puede contener números.')

        if not apellido or len(apellido) < 2:
            errors.append('El apellido debe tener al menos 2 caracteres.')
        elif any(c.isdigit() for c in apellido):
            errors.append('El apellido no puede contener números.')

        try:
            validate_email(email)
        except ValidationError:
            errors.append('Ingresa un correo electrónico válido.')
        else:
            if UserModel.objects.filter(email__iexact=email).exists():
                errors.append('Este correo ya está registrado.')

        if len(password) < 8:
            errors.append('La contraseña debe tener al menos 8 caracteres.')
        elif not any(c.isupper() for c in password):
            errors.append('La contraseña debe tener al menos una letra mayúscula.')
        elif not any(c.isdigit() for c in password):
            errors.append('La contraseña debe contener al menos un número.')

        if password != password2:
            errors.append('Las contraseñas no coinciden.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'auth/register.html', {'posted': posted}, status=400)

        try:
            CreateUserUseCase(UserRepositoryImpl()).execute(
                {
                    'nombre': nombre,
                    'apellido': apellido,
                    'email': email,
                    'password': password,
                    'rol_id': rol_cliente.id_rol,
                    'activo': True,
                    'is_staff': False,
                    'is_superuser': False,
                }
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, 'auth/register.html', {'posted': posted}, status=400)

        messages.success(request, '¡Cuenta creada! Inicia sesión con tus credenciales.')

        # Enviar bienvenida + promociones actuales al nuevo cliente
        try:
            from users.utils.sendpulse import enviar_promocion_a_clientes
            enviar_promocion_a_clientes(
                subject='¡Bienvenido a Olla y Sazón! Conoce nuestras promociones',
                html_body=(
                    f'<h2>Hola {nombre}, bienvenido/a a Olla y Sazón 🍽️</h2>'
                    '<p>Gracias por registrarte. A partir de ahora recibirás '
                    'nuestras mejores promociones y noticias del restaurante.</p>'
                ),
            )
        except Exception as exc:
            if getattr(django_settings, 'DEBUG', False):
                print('SendPulse registro error:', exc)

        return redirect('login')

    return render(request, 'auth/register.html', {'posted': None})


@never_cache
def logout_view(request):
    if request.method == 'POST':
        logout(request)
    response = redirect('login')
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    # Ayuda a que el navegador no siga mostrando HTML del panel desde caché (Chrome/Edge/Firefox recientes)
    response['Clear-Site-Data'] = '"cache"'
    return response
