import os
import uuid
from datetime import date, datetime, time as dt_time
from functools import wraps

from django.utils import timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Count, ProtectedError
from django.http import Http404
from django.shortcuts import redirect, render

from users.application.application.use_cases.categoria_usecase import (
    ActualizarCategoriaUseCase,
    CrearCategoriaUseCase,
    EliminarCategoriaUseCase,
    ObtenerCategoriaUseCase,
)
from users.application.application.use_cases.horario_usecase import CrearHorarioUseCase
from users.application.application.use_cases.inventario_usecase import CrearOActualizarInventarioUseCase
from users.application.application.use_cases.mesa_usecase import (
    ActualizarMesaUseCase,
    CrearMesaUseCase,
    ObtenerMesaUseCase,
)
from users.application.application.use_cases.noticia_usecase import CrearNoticiaUseCase
from users.application.application.use_cases.pago_usecase import CrearPagoUseCase
from users.application.application.use_cases.pedido_usecase import (
    ActualizarPedidoUseCase,
    CambiarEstadoPedidoUseCase,
    CrearPedidoUseCase,
)
from users.application.application.use_cases.producto_usecase import (
    ActualizarProductoUseCase,
    CrearProductoUseCase,
)
from users.application.application.use_cases.promocion_usecase import (
    ActualizarPromocionCompletaUseCase,
    CrearPromocionUseCase,
    EliminarPromocionUseCase,
)
from users.application.application.use_cases.reserva_usecase import CrearReservaUseCase
from users.application.application.use_cases.user_usecases import (
    CreateUserUseCase,
    DeleteUserUseCase,
    GetUserUseCase,
    ListUsersUseCase,
    UpdateUserUseCase,
)
from users.infrastructure.models import (
    CategoriaModel,
    InventarioModel,
    MesaModel,
    ModuloBloqueoModel,
    PagoModel,
    PedidoModel,
    ProductoModel,
    PromocionModel,
    ReservaModel,
    RolModel,
    UserModel,
    SolicitudCambioTurnoModel,
)
from users.infrastructure.models.horario_model import HorarioModel
from users.infrastructure.repositories.categoria_repository_impl import CategoriaRepositoryImpl
from users.infrastructure.repositories.horario_repository_impl import HorarioRepositoryImpl
from users.infrastructure.repositories.inventario_repository_impl import InventarioRepositoryImpl
from users.infrastructure.repositories.mesa_repository_impl import MesaRepositoryImpl
from users.infrastructure.repositories.noticia_repository_impl import NoticiaRepositoryImpl
from users.infrastructure.repositories.pago_repository_impl import PagoRepositoryImpl
from users.infrastructure.repositories.pedido_repository_impl import PedidoRepositoryImpl
from users.infrastructure.repositories.producto_repository_impl import ProductoRepositoryImpl
from users.infrastructure.repositories.promocion_repository_impl import PromocionRepositoryImpl
from users.infrastructure.repositories.reserva_repository_impl import ReservaRepositoryImpl
from users.infrastructure.repositories.user_repository_impl import UserRepositoryImpl
from users.infrastructure.views.panel_views import _rol_upper


class _UserListRow:
    """Adaptador para plantillas que esperan `.rol` (modelo) y `.pk`."""

    __slots__ = ('id_user', 'pk', 'nombre', 'apellido', 'email', 'activo', 'rol')

    def __init__(self, entity, rol):
        self.id_user = entity.id_user
        self.pk = entity.id_user
        self.nombre = entity.nombre
        self.apellido = entity.apellido
        self.email = entity.email
        self.activo = entity.activo
        self.rol = rol


def _user_repository():
    return UserRepositoryImpl()


def _categoria_repository():
    return CategoriaRepositoryImpl()


def _producto_repository():
    return ProductoRepositoryImpl()


def _save_media_upload(subfolder: str, uploaded_file):
    ext = os.path.splitext((uploaded_file.name or ''))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        raise ValueError('La imagen debe ser JPG, PNG, GIF o WEBP.')
    rel = f'{subfolder}/{uuid.uuid4().hex}{ext}'
    saved = default_storage.save(rel, uploaded_file)
    base = settings.MEDIA_URL.rstrip('/')
    path = saved.replace('\\', '/')
    return f'{base}/{path}'


def _save_product_image_upload(uploaded_file):
    return _save_media_upload('productos', uploaded_file)


def _save_promotion_image_upload(uploaded_file):
    return _save_media_upload('promociones', uploaded_file)


def _promocion_repository():
    return PromocionRepositoryImpl()


def _inventario_repository():
    return InventarioRepositoryImpl()


def _mesa_repository():
    return MesaRepositoryImpl()


def _reserva_repository():
    return ReservaRepositoryImpl()


def _pedido_repository():
    return PedidoRepositoryImpl()


def _pago_repository():
    return PagoRepositoryImpl()


def _horario_repository():
    return HorarioRepositoryImpl()


def _noticia_repository():
    return NoticiaRepositoryImpl()


def _save_noticia_image_upload(uploaded_file):
    return _save_media_upload('noticias', uploaded_file)


def _optional_int(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _empleados_queryset():
    return (
        UserModel.objects.filter(activo=True, rol__nombre__iexact='EMPLEADO')
        .select_related('rol')
        .order_by('nombre', 'apellido')
    )


def _clientes_queryset():
    return (
        UserModel.objects.filter(activo=True, rol__nombre__iexact='CLIENTE')
        .select_related('rol')
        .order_by('nombre', 'apellido')
    )


def admin_only(view_func):
    @wraps(view_func)
    @login_required(login_url='/login/')
    def _wrapped(request, *args, **kwargs):
        rol = _rol_upper(request.user)
        es_admin = rol == 'ADMINISTRADOR' or request.user.is_superuser or request.user.is_staff
        if not es_admin:
            messages.warning(request, 'No tienes permiso para acceder a esa sección.')
            if rol == 'EMPLEADO':
                return redirect('pedidos_asignados')
            return redirect('mi_perfil')
        return view_func(request, *args, **kwargs)
    return _wrapped


@admin_only
def users_list_view(request):
    repo = _user_repository()
    entities = ListUsersUseCase(repo).execute()
    rol_ids = {e.rol_id for e in entities if e.rol_id}
    roles_by_id = (
        {r.id_rol: r for r in RolModel.objects.filter(id_rol__in=rol_ids)}
        if rol_ids
        else {}
    )
    usuarios = [_UserListRow(e, roles_by_id.get(e.rol_id)) for e in entities]
    return render(request, 'admin/users_list.html', {'usuarios': usuarios})


@admin_only
def user_toggle_bloqueo_view(request, pk):
    if request.method != 'POST':
        return redirect('admin_users')
    try:
        target = UserModel.objects.get(pk=pk)
    except UserModel.DoesNotExist:
        raise Http404
    if target.pk == request.user.pk:
        messages.error(request, 'No puedes bloquearte a ti mismo.')
        return redirect('admin_users')
    target.activo = not target.activo
    target.save(update_fields=['activo'])
    estado = 'desbloqueada' if target.activo else 'bloqueada'
    messages.success(request, f'Cuenta de {target.nombre} {target.apellido} {estado} correctamente.')
    return redirect('admin_users')


@admin_only
def user_create_view(request):
    repo = _user_repository()
    roles = RolModel.objects.order_by('nombre')

    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        apellido = (request.POST.get('apellido') or '').strip()
        email = (request.POST.get('email') or '').strip().lower()

        rol_raw = (request.POST.get('rol') or '').strip()
        rol_id = None
        if rol_raw:
            try:
                rol_id = int(rol_raw)
            except ValueError:
                rol_id = None

        password1 = (request.POST.get('password1') or '').strip()
        password2 = (request.POST.get('password2') or '').strip()
        activo = bool(request.POST.get('activo'))
        is_staff = bool(request.POST.get('is_staff'))
        is_superuser = bool(request.POST.get('is_superuser'))

        if password1 != password2:
            messages.error(request, 'Las contraseñas no coinciden.')
            return render(
                request,
                'admin/user_create_form.html',
                {
                    'roles': roles,
                    'posted': request.POST,
                },
                status=400,
            )

        data = {
            'nombre': nombre,
            'apellido': apellido,
            'email': email,
            'password': password1,
            'rol_id': rol_id,
            'activo': activo,
            'is_staff': is_staff,
            'is_superuser': is_superuser,
        }

        try:
            CreateUserUseCase(repo).execute(data)
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                'admin/user_create_form.html',
                {
                    'roles': roles,
                    'posted': request.POST,
                },
                status=400,
            )

        messages.success(request, 'Usuario creado correctamente.')
        return redirect('admin_users')

    return render(
        request,
        'admin/user_create_form.html',
        {'roles': roles},
    )


@admin_only
def user_edit_view(request, pk):
    repo = _user_repository()
    roles = RolModel.objects.order_by('nombre')

    if request.method == 'POST':
        pwd1 = (request.POST.get('new_password1') or '').strip()
        pwd2 = (request.POST.get('new_password2') or '').strip()
        rol_raw = (request.POST.get('rol') or '').strip()
        rol_id = None
        if rol_raw:
            try:
                rol_id = int(rol_raw)
            except ValueError:
                rol_id = None

        data = {
            'nombre': (request.POST.get('nombre') or '').strip(),
            'apellido': (request.POST.get('apellido') or '').strip(),
            'email': (request.POST.get('email') or '').strip().lower(),
            'activo': bool(request.POST.get('activo')),
            'is_staff': bool(request.POST.get('is_staff')),
            'is_superuser': bool(request.POST.get('is_superuser')),
            'rol_id': rol_id,
        }
        if pwd1 or pwd2:
            if pwd1 != pwd2:
                messages.error(request, 'Las contraseñas nuevas no coinciden.')
                try:
                    edit_user = GetUserUseCase(repo).execute(pk)
                except LookupError:
                    raise Http404
                return render(
                    request,
                    'admin/user_form.html',
                    {'edit_user': edit_user, 'roles': roles},
                    status=400,
                )
            data['new_password'] = pwd1

        try:
            UpdateUserUseCase(repo).execute(pk, data)
        except ValueError as exc:
            messages.error(request, str(exc))
            try:
                edit_user = GetUserUseCase(repo).execute(pk)
            except LookupError:
                raise Http404
            return render(
                request,
                'admin/user_form.html',
                {'edit_user': edit_user, 'roles': roles},
                status=400,
            )
        except LookupError:
            raise Http404

        messages.success(request, 'Usuario actualizado correctamente.')
        return redirect('admin_users')

    try:
        edit_user = GetUserUseCase(repo).execute(pk)
    except LookupError:
        raise Http404
    return render(request, 'admin/user_form.html', {'edit_user': edit_user, 'roles': roles})


@admin_only
def user_delete_view(request, pk):
    repo = _user_repository()
    try:
        target = GetUserUseCase(repo).execute(pk)
    except LookupError:
        raise Http404

    if target.id_user == request.user.pk:
        messages.error(request, 'No puedes eliminar tu propia cuenta.')
        return redirect('admin_users')

    if request.method == 'POST':
        try:
            DeleteUserUseCase(repo).execute(pk)
        except ProtectedError:
            messages.error(
                request,
                'No se puede eliminar: el usuario está referenciado en pedidos u otros registros protegidos.',
            )
            return redirect('admin_users')
        except LookupError:
            messages.error(request, 'No se pudo eliminar el usuario.')
            return redirect('admin_users')
        messages.success(request, 'Usuario eliminado.')
        return redirect('admin_users')

    return render(request, 'admin/user_confirm_delete.html', {'target_user': target})


@admin_only
def categorias_list_view(request):
    categorias = CategoriaModel.objects.all().order_by('nombre')
    return render(request, 'admin/categorias_list.html', {'categorias': categorias})


@admin_only
def categoria_create_view(request):
    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        if not nombre:
            messages.error(request, 'El nombre es obligatorio.')
            return render(request, 'admin/categoria_form.html', {'edit_categoria': None}, status=400)
        try:
            CrearCategoriaUseCase(_categoria_repository()).execute(nombre=nombre, descripcion=descripcion or None)
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, 'admin/categoria_form.html', {'edit_categoria': None}, status=400)
        messages.success(request, 'Categoría creada correctamente.')
        return redirect('admin_categorias')
    return render(request, 'admin/categoria_form.html', {'edit_categoria': None})


@admin_only
def categoria_delete_view(request, pk):
    try:
        categoria = CategoriaModel.objects.get(pk=pk)
    except CategoriaModel.DoesNotExist:
        raise Http404
    if request.method == 'POST':
        try:
            EliminarCategoriaUseCase(_categoria_repository()).execute(pk)
            messages.success(request, 'Categoría eliminada.')
        except ProtectedError:
            messages.error(request, 'No se puede eliminar: tiene productos asociados.')
        except LookupError:
            messages.error(request, 'No se pudo eliminar la categoría.')
        return redirect('admin_categorias')
    return render(request, 'admin/categoria_confirm_delete.html', {'categoria': categoria})


@admin_only
def categoria_edit_view(request, pk):
    repo = _categoria_repository()
    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        if not nombre:
            messages.error(request, 'El nombre es obligatorio.')
            try:
                edit_categoria = ObtenerCategoriaUseCase(repo).execute(pk)
            except LookupError:
                raise Http404
            return render(
                request,
                'admin/categoria_form.html',
                {'edit_categoria': edit_categoria},
                status=400,
            )
        try:
            ActualizarCategoriaUseCase(repo).execute(pk, nombre=nombre, descripcion=descripcion)
        except LookupError:
            raise Http404
        except ValueError as exc:
            messages.error(request, str(exc))
            try:
                edit_categoria = ObtenerCategoriaUseCase(repo).execute(pk)
            except LookupError:
                raise Http404
            return render(
                request,
                'admin/categoria_form.html',
                {'edit_categoria': edit_categoria},
                status=400,
            )
        messages.success(request, 'Categoría actualizada correctamente.')
        return redirect('admin_categorias')

    try:
        edit_categoria = ObtenerCategoriaUseCase(repo).execute(pk)
    except LookupError:
        raise Http404
    return render(request, 'admin/categoria_form.html', {'edit_categoria': edit_categoria})


@admin_only
def producto_create_view(request):
    categorias = CategoriaModel.objects.order_by('nombre')
    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        precio_raw = (request.POST.get('precio') or '').strip().replace("$", "").replace(" ", "")
        categoria_raw = (request.POST.get('categoria_id') or '').strip()
        imagen_url_manual = (request.POST.get('imagen_url') or '').strip()

        if not nombre:
            messages.error(request, 'El nombre es obligatorio.')
            return render(
                request,
                'admin/producto_form.html',
                {'categorias': categorias, 'posted': request.POST},
                status=400,
            )

        try:
            precio = float(precio_raw.replace(',', '.'))
        except ValueError:
            precio = 0.0

        try:
            categoria_id = int(categoria_raw)
        except ValueError:
            categoria_id = None

        if not categoria_id or not CategoriaModel.objects.filter(pk=categoria_id).exists():
            messages.error(request, 'Selecciona una categoría válida.')
            return render(
                request,
                'admin/producto_form.html',
                {'categorias': categorias, 'posted': request.POST},
                status=400,
            )

        imagen_url = imagen_url_manual or None
        if request.FILES.get('imagen'):
            try:
                imagen_url = _save_product_image_upload(request.FILES['imagen'])
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    'admin/producto_form.html',
                    {'categorias': categorias, 'posted': request.POST},
                    status=400,
                )

        data = {
            'nombre': nombre,
            'descripcion': descripcion or None,
            'precio': precio,
            'categoria_id': categoria_id,
            'imagen_url': imagen_url,
        }

        try:
            CrearProductoUseCase(_producto_repository()).execute(data)
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                'admin/producto_form.html',
                {'categorias': categorias, 'posted': request.POST},
                status=400,
            )

        messages.success(request, 'Producto creado correctamente.')
        return redirect('admin_productos')

    return render(request, 'admin/producto_form.html', {'categorias': categorias, 'posted': None})


@admin_only
def producto_edit_view(request, pk):
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise Http404
    categorias = CategoriaModel.objects.order_by('nombre')
    try:
        edit_producto = ProductoModel.objects.select_related('categoria').get(pk=pk)
    except ProductoModel.DoesNotExist:
        raise Http404

    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        precio_raw = (request.POST.get('precio') or '').strip().replace("$", "").replace(" ", "")
        categoria_raw = (request.POST.get('categoria_id') or '').strip()
        imagen_url_manual = (request.POST.get('imagen_url') or '').strip()

        if not nombre:
            messages.error(request, 'El nombre es obligatorio.')
            return render(
                request,
                'admin/producto_form.html',
                {
                    'categorias': categorias,
                    'posted': request.POST,
                    'edit_producto': edit_producto,
                },
                status=400,
            )

        try:
            precio = float(precio_raw.replace(',', '.'))
        except ValueError:
            precio = 0.0

        try:
            categoria_id = int(categoria_raw)
        except ValueError:
            categoria_id = None

        if not categoria_id or not CategoriaModel.objects.filter(pk=categoria_id).exists():
            messages.error(request, 'Selecciona una categoría válida.')
            return render(
                request,
                'admin/producto_form.html',
                {
                    'categorias': categorias,
                    'posted': request.POST,
                    'edit_producto': edit_producto,
                },
                status=400,
            )

        if request.FILES.get('imagen'):
            try:
                imagen_url = _save_product_image_upload(request.FILES['imagen'])
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    'admin/producto_form.html',
                    {
                        'categorias': categorias,
                        'posted': request.POST,
                        'edit_producto': edit_producto,
                    },
                    status=400,
                )
        else:
            imagen_url = imagen_url_manual or None

        data = {
            'nombre': nombre,
            'descripcion': descripcion or None,
            'precio': precio,
            'categoria_id': categoria_id,
            'imagen_url': imagen_url,
        }

        try:
            ActualizarProductoUseCase(_producto_repository()).execute(pk, data)
        except LookupError:
            raise Http404
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                'admin/producto_form.html',
                {
                    'categorias': categorias,
                    'posted': request.POST,
                    'edit_producto': edit_producto,
                },
                status=400,
            )

        messages.success(request, 'Producto actualizado correctamente.')
        return redirect('admin_productos')

    return render(
        request,
        'admin/producto_form.html',
        {'categorias': categorias, 'posted': None, 'edit_producto': edit_producto},
    )


@admin_only
def productos_list_view(request):
    qs = ProductoModel.objects.select_related('categoria').order_by('categoria__nombre', 'nombre')
    nombre = (request.GET.get('nombre') or '').strip()
    if nombre:
        qs = qs.filter(nombre__icontains=nombre)
    return render(
        request,
        'admin/productos_list.html',
        {'productos': qs, 'filtro_nombre': nombre},
    )


def _promocion_form_context(productos_qs, posted=None, edit_promocion=None):
    if posted is not None:
        sel = posted.getlist('productos')
    elif edit_promocion is not None:
        sel = [str(x) for x in edit_promocion.productos.values_list('id_producto', flat=True)]
    else:
        sel = []
    return {
        'productos': productos_qs,
        'posted': posted,
        'selected_productos': sel,
        'edit_promocion': edit_promocion,
    }


@admin_only
def promocion_create_view(request):
    productos = ProductoModel.objects.select_related('categoria').order_by('categoria__nombre', 'nombre')

    if request.method == 'POST':
        titulo = (request.POST.get('titulo') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        descuento_raw = (request.POST.get('descuento') or '').strip()
        fi = (request.POST.get('fecha_inicio') or '').strip()
        ff = (request.POST.get('fecha_fin') or '').strip()
        imagen_url_manual = (request.POST.get('imagen_url') or '').strip()

        product_ids = []
        for x in request.POST.getlist('productos'):
            try:
                product_ids.append(int(x))
            except ValueError:
                continue

        if not titulo:
            messages.error(request, 'El título es obligatorio.')
            return render(
                request,
                'admin/promocion_form.html',
                _promocion_form_context(productos, request.POST),
                status=400,
            )

        try:
            descuento = float(descuento_raw.replace(',', '.'))
        except ValueError:
            descuento = 0.0

        try:
            fecha_inicio = date.fromisoformat(fi)
            fecha_fin = date.fromisoformat(ff)
        except ValueError:
            messages.error(request, 'Indica fechas válidas (formato AAAA-MM-DD).')
            return render(
                request,
                'admin/promocion_form.html',
                _promocion_form_context(productos, request.POST),
                status=400,
            )

        imagen_url = imagen_url_manual or None
        if request.FILES.get('imagen'):
            try:
                imagen_url = _save_promotion_image_upload(request.FILES['imagen'])
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    'admin/promocion_form.html',
                    _promocion_form_context(productos, request.POST),
                    status=400,
                )

        try:
            CrearPromocionUseCase(_promocion_repository()).execute(
                titulo,
                descuento,
                fecha_inicio,
                fecha_fin,
                descripcion=descripcion or None,
                imagen_url=imagen_url,
                productos=product_ids,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                'admin/promocion_form.html',
                _promocion_form_context(productos, request.POST),
                status=400,
            )

        messages.success(request, 'Promoción creada correctamente.')
        return redirect('admin_promociones')

    return render(request, 'admin/promocion_form.html', _promocion_form_context(productos))


@admin_only
def promocion_edit_view(request, pk):
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise Http404
    productos = ProductoModel.objects.select_related('categoria').order_by('categoria__nombre', 'nombre')
    try:
        edit_promocion = PromocionModel.objects.prefetch_related('productos').get(pk=pk)
    except PromocionModel.DoesNotExist:
        raise Http404

    if request.method == 'POST':
        titulo = (request.POST.get('titulo') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        descuento_raw = (request.POST.get('descuento') or '').strip()
        fi = (request.POST.get('fecha_inicio') or '').strip()
        ff = (request.POST.get('fecha_fin') or '').strip()
        imagen_url_manual = (request.POST.get('imagen_url') or '').strip()

        product_ids = []
        for x in request.POST.getlist('productos'):
            try:
                product_ids.append(int(x))
            except ValueError:
                continue

        if not titulo:
            messages.error(request, 'El título es obligatorio.')
            return render(
                request,
                'admin/promocion_form.html',
                _promocion_form_context(productos, request.POST, edit_promocion),
                status=400,
            )

        try:
            descuento = float(descuento_raw.replace(',', '.'))
        except ValueError:
            descuento = 0.0

        try:
            fecha_inicio = date.fromisoformat(fi)
            fecha_fin = date.fromisoformat(ff)
        except ValueError:
            messages.error(request, 'Indica fechas válidas (formato AAAA-MM-DD).')
            return render(
                request,
                'admin/promocion_form.html',
                _promocion_form_context(productos, request.POST, edit_promocion),
                status=400,
            )

        if request.FILES.get('imagen'):
            try:
                imagen_url = _save_promotion_image_upload(request.FILES['imagen'])
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    'admin/promocion_form.html',
                    _promocion_form_context(productos, request.POST, edit_promocion),
                    status=400,
                )
        else:
            imagen_url = imagen_url_manual or None

        try:
            ActualizarPromocionCompletaUseCase(_promocion_repository()).execute(
                pk,
                titulo,
                descuento,
                fecha_inicio,
                fecha_fin,
                descripcion=descripcion or None,
                imagen_url=imagen_url,
                productos=product_ids,
            )
        except LookupError:
            raise Http404
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                'admin/promocion_form.html',
                _promocion_form_context(productos, request.POST, edit_promocion),
                status=400,
            )

        messages.success(request, 'Promoción actualizada correctamente.')
        return redirect('admin_promociones')

    return render(
        request,
        'admin/promocion_form.html',
        _promocion_form_context(productos, edit_promocion=edit_promocion),
    )


@admin_only
def promocion_delete_view(request, pk):
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise Http404
    try:
        promocion = PromocionModel.objects.get(pk=pk)
    except PromocionModel.DoesNotExist:
        raise Http404

    if request.method == 'POST':
        try:
            EliminarPromocionUseCase(_promocion_repository()).execute(pk)
        except LookupError:
            messages.error(request, 'No se pudo eliminar la promoción.')
            return redirect('admin_promociones')
        messages.success(request, 'Promoción eliminada.')
        return redirect('admin_promociones')

    return render(request, 'admin/promocion_confirm_delete.html', {'promocion': promocion})


@admin_only
def inventario_create_view(request):
    productos = ProductoModel.objects.select_related('categoria').order_by('categoria__nombre', 'nombre')
    if request.method == 'POST':
        raw_pid = (request.POST.get('producto_id') or '').strip()
        raw_cd = (request.POST.get('cantidad_disponible') or '').strip()
        raw_cm = (request.POST.get('cantidad_minima') or '').strip()

        try:
            producto_id = int(raw_pid)
        except ValueError:
            producto_id = None

        if not producto_id or not ProductoModel.objects.filter(pk=producto_id).exists():
            messages.error(request, 'Selecciona un producto válido.')
            return render(
                request,
                'admin/inventario_form.html',
                {'productos': productos, 'posted': request.POST},
                status=400,
            )

        try:
            cantidad_disponible = int(raw_cd)
            cantidad_minima = int(raw_cm)
        except ValueError:
            messages.error(request, 'Las cantidades deben ser números enteros.')
            return render(
                request,
                'admin/inventario_form.html',
                {'productos': productos, 'posted': request.POST},
                status=400,
            )

        try:
            CrearOActualizarInventarioUseCase(_inventario_repository()).execute(
                producto_id,
                cantidad_disponible,
                cantidad_minima,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                'admin/inventario_form.html',
                {'productos': productos, 'posted': request.POST},
                status=400,
            )

        messages.success(request, 'Inventario guardado correctamente en la base de datos.')
        return redirect('admin_inventario')

    return render(request, 'admin/inventario_form.html', {'productos': productos, 'posted': None})


@admin_only
def promociones_list_view(request):
    promociones = PromocionModel.objects.prefetch_related('productos').order_by('-fecha_inicio')
    return render(request, 'admin/promociones_list.html', {'promociones': promociones})


@admin_only
def inventario_list_view(request):
    items = InventarioModel.objects.select_related('producto').order_by('producto__nombre')
    return render(request, 'admin/inventario_list.html', {'items': items})


@admin_only
def mesas_list_view(request):
    mesas = MesaModel.objects.all().order_by('numero_mesa')
    return render(request, 'admin/mesas_list.html', {'mesas': mesas})


ADMIN_PEDIDO_TRANSICIONES = {
    'PENDIENTE': ['EN_PREPARACION', 'CANCELADO'],
    'EN_PREPARACION': ['LISTO', 'CANCELADO'],
    'LISTO': ['ENTREGADO', 'CANCELADO'],
    'ENTREGADO': [],
    'CANCELADO': [],
}


@admin_only
def reservas_list_view(request):
    if request.method == 'POST':
        reserva_id = _optional_int(request.POST.get('reserva_id'))
        accion = (request.POST.get('accion') or '').strip().lower()
        reserva = (
            ReservaModel.objects.filter(pk=reserva_id).select_related('mesa', 'user').first()
            if reserva_id
            else None
        )
        if not reserva:
            messages.error(request, 'Reserva no encontrada.')
            return redirect('admin_reservas')
        est = (reserva.estado or '').strip().upper()
        if accion == 'confirmar':
            if est != 'PENDIENTE':
                messages.warning(request, 'Solo se pueden confirmar reservas en estado PENDIENTE.')
            else:
                ReservaModel.objects.filter(pk=reserva_id).update(estado='CONFIRMADA')
                reserva.refresh_from_db()
                from users.services.sendpulse_service import enviar_correo_confirmacion
                enviar_correo_confirmacion(reserva)
                messages.success(request, 'Reserva confirmada.')
        elif accion == 'cancelar':
            if est in ('CANCELADA', 'CANCELADO', 'COMPLETADA'):
                messages.warning(request, 'Esta reserva ya no admite cancelación desde aquí.')
            else:
                ReservaModel.objects.filter(pk=reserva_id).update(estado='CANCELADA')
                reserva.refresh_from_db()
                from users.services.sendpulse_service import enviar_correo_rechazo
                enviar_correo_rechazo(reserva)
                messages.success(request, 'Reserva cancelada.')
        else:
            messages.error(request, 'Acción no válida.')
        return redirect('admin_reservas')

    reservas = ReservaModel.objects.select_related('mesa', 'user').order_by('-fecha_reserva')
    return render(request, 'admin/reservas_list.html', {'reservas': reservas})


@admin_only
def pedidos_list_view(request):
    repo = PedidoRepositoryImpl()
    if request.method == 'POST':
        accion = (request.POST.get('accion') or '').strip().lower()
        if accion == 'asignar_mesero':
            pedido_id = _optional_int(request.POST.get('pedido_id'))
            empleado_id = _optional_int(request.POST.get('empleado_id'))
            pedido = PedidoModel.objects.filter(pk=pedido_id).first() if pedido_id else None
            if not pedido:
                messages.error(request, 'Pedido no encontrado.')
                return redirect('admin_pedidos')

            if not empleado_id:
                PedidoModel.objects.filter(pk=pedido.id).update(empleado_asignado=None)
                messages.success(request, f'Se desasigno el mesero del pedido #{pedido.id}.')
                return redirect('admin_pedidos')

            empleado = (
                UserModel.objects.filter(
                    pk=empleado_id,
                    activo=True,
                    rol__nombre__iexact='EMPLEADO',
                ).first()
            )
            if not empleado:
                messages.error(request, 'El mesero seleccionado no es valido.')
                return redirect('admin_pedidos')

            PedidoModel.objects.filter(pk=pedido.id).update(empleado_asignado=empleado)
            messages.success(
                request,
                f'Pedido #{pedido.id} asignado a {empleado.nombre} {empleado.apellido}.',
            )
            return redirect('admin_pedidos')

        pedido_id = _optional_int(request.POST.get('pedido_id'))
        nuevo_estado = (request.POST.get('nuevo_estado') or '').strip().upper()
        if not pedido_id or not nuevo_estado:
            messages.error(request, 'Datos del formulario inválidos.')
            return redirect('admin_pedidos')
        pedido = PedidoModel.objects.filter(pk=pedido_id).first()
        if not pedido:
            messages.error(request, 'Pedido no encontrado.')
            return redirect('admin_pedidos')
        allowed = ADMIN_PEDIDO_TRANSICIONES.get((pedido.estado or '').strip().upper(), [])
        if nuevo_estado not in allowed:
            messages.error(request, 'No se puede pasar el pedido a ese estado desde el actual.')
            return redirect('admin_pedidos')
        try:
            CambiarEstadoPedidoUseCase(repo).execute(pedido_id, nuevo_estado)
            messages.success(request, f'Pedido #{pedido_id} actualizado a «{nuevo_estado}».')
        except Exception as exc:
            messages.error(request, f'No se pudo actualizar el pedido: {exc}')
        return redirect('admin_pedidos')

    empleados_meseros = list(
        UserModel.objects.filter(activo=True, rol__nombre__iexact='EMPLEADO')
        .order_by('nombre', 'apellido')
    )
    pedidos = list(
        PedidoModel.objects.select_related('user', 'empleado_asignado')
        .prefetch_related('detalles__producto')
        .order_by('-fecha_creacion')
    )
    for p in pedidos:
        p.allowed_next = ADMIN_PEDIDO_TRANSICIONES.get((p.estado or '').strip().upper(), [])
    return render(
        request,
        'admin/pedidos_list.html',
        {
            'pedidos': pedidos,
            'empleados_meseros': empleados_meseros,
        },
    )


@admin_only
def pagos_list_view(request):
    if request.method == 'POST':
        pago_id = _optional_int(request.POST.get('pago_id'))
        accion = (request.POST.get('accion') or '').strip().lower()
        pago = PagoModel.objects.filter(pk=pago_id).first() if pago_id else None
        if not pago:
            messages.error(request, 'Pago no encontrado.')
            return redirect('admin_pagos')
        est = (pago.estado or '').strip().upper()
        if accion == 'aceptar':
            if est != 'PENDIENTE':
                messages.warning(request, 'Solo se pueden aceptar pagos pendientes.')
            else:
                PagoModel.objects.filter(pk=pago_id).update(
                    estado='COMPLETADO',
                    fecha_pago=date.today(),
                )
                pago.refresh_from_db()
                from users.services.sendpulse_service import enviar_correo_pago_aprobado
                enviar_correo_pago_aprobado(pago)
                messages.success(request, 'Pago aceptado y marcado como completado.')
        elif accion == 'rechazar':
            if est != 'PENDIENTE':
                messages.warning(request, 'Solo se pueden rechazar pagos pendientes.')
            else:
                motivo = (request.POST.get('motivo_rechazo') or '').strip()
                if not motivo:
                    messages.error(request, 'Debes indicar el motivo del rechazo.')
                    return redirect('admin_pagos')
                PagoModel.objects.filter(pk=pago_id).update(
                    estado='RECHAZADO',
                    motivo_rechazo=motivo,
                )
                pago.refresh_from_db()
                from users.services.sendpulse_service import enviar_correo_pago_rechazado
                enviar_correo_pago_rechazado(pago)
                messages.success(request, 'Pago rechazado.')
        else:
            messages.error(request, 'Acción no válida.')
        return redirect('admin_pagos')

    pagos = PagoModel.objects.select_related('user', 'pedido').order_by('-fecha_creacion')
    return render(request, 'admin/pagos_list.html', {'pagos': pagos})


@admin_only
def empleados_list_view(request):
    """Listado filtrado de usuarios con rol EMPLEADO."""
    repo = _user_repository()
    entities = ListUsersUseCase(repo).execute()
    rol_ids = {e.rol_id for e in entities if e.rol_id}
    roles_by_id = (
        {r.id_rol: r for r in RolModel.objects.filter(id_rol__in=rol_ids)}
        if rol_ids
        else {}
    )
    usuarios = [
        _UserListRow(e, roles_by_id.get(e.rol_id))
        for e in entities
        if roles_by_id.get(e.rol_id)
        and (roles_by_id.get(e.rol_id).nombre or '').strip().upper() == 'EMPLEADO'
    ]
    return render(
        request,
        'admin/empleados_list.html',
        {'usuarios': usuarios},
    )


@admin_only
def clientes_fieles_view(request):
    umbral = max(1, int((request.GET.get('umbral') or '3').strip() or 3))
    clientes = (
        UserModel.objects
        .filter(activo=True, rol__nombre__iexact='CLIENTE')
        .annotate(total_pedidos=Count('pedidos_cliente', distinct=True))
        .filter(total_pedidos__gte=umbral)
        .order_by('-total_pedidos')
    )
    return render(request, 'admin/clientes_fieles.html', {'clientes': clientes, 'umbral': umbral})


@admin_only
def modulos_bloqueo_view(request):
    MODULOS_DISPONIBLES = [
        {'nombre': 'Menú',        'url_patron': '/menu/'},
        {'nombre': 'Reservas',    'url_patron': '/reserva/'},
        {'nombre': 'Carrito',     'url_patron': '/carrito/'},
        {'nombre': 'Noticias',    'url_patron': '/noticias/'},
        {'nombre': 'Promociones', 'url_patron': '/promociones/'},
        {'nombre': 'Pedidos',     'url_patron': '/pedidos/'},
        {'nombre': 'Pagos',       'url_patron': '/pagos/'},
    ]

    if request.method == 'POST':
        accion = (request.POST.get('accion') or '').strip()
        url_patron = (request.POST.get('url_patron') or '').strip()
        motivo = (request.POST.get('motivo') or '').strip()
        nombre = next((m['nombre'] for m in MODULOS_DISPONIBLES if m['url_patron'] == url_patron), url_patron)

        if accion == 'bloquear':
            ModuloBloqueoModel.objects.update_or_create(
                url_patron=url_patron,
                defaults={'nombre': nombre, 'motivo': motivo, 'bloqueado': True},
            )
            messages.success(request, f'Módulo «{nombre}» bloqueado correctamente.')
        elif accion == 'desbloquear':
            ModuloBloqueoModel.objects.filter(url_patron=url_patron).update(bloqueado=False)
            messages.success(request, f'Módulo «{nombre}» desbloqueado correctamente.')
        return redirect('admin_modulos_bloqueo')

    bloqueados = {m.url_patron: m for m in ModuloBloqueoModel.objects.filter(bloqueado=True)}
    modulos = []
    for m in MODULOS_DISPONIBLES:
        bloqueo = bloqueados.get(m['url_patron'])
        modulos.append({
            'nombre': m['nombre'],
            'url_patron': m['url_patron'],
            'bloqueado': bloqueo is not None,
            'motivo': bloqueo.motivo if bloqueo else '',
        })
    return render(request, 'admin/modulos_bloqueo.html', {'modulos': modulos})


@admin_only
def horarios_list_view(request):
    horarios = HorarioModel.objects.select_related('user').order_by('user__nombre', 'dia_semana')
    return render(request, 'admin/horarios_list.html', {'horarios': horarios})


MESA_ESTADOS = (
    ('libre', 'libre'),
    ('ocupada', 'ocupada'),
    ('reservada', 'reservada'),
)

RESERVA_ESTADOS = (
    ('PENDIENTE', 'PENDIENTE'),
    ('CONFIRMADA', 'CONFIRMADA'),
    ('CANCELADA', 'CANCELADA'),
    ('COMPLETADA', 'COMPLETADA'),
)

PEDIDO_ESTADOS = (
    ('PENDIENTE', 'PENDIENTE'),
    ('EN_PREPARACION', 'EN_PREPARACION'),
    ('LISTO', 'LISTO'),
    ('ENTREGADO', 'ENTREGADO'),
    ('CANCELADO', 'CANCELADO'),
)

PAGO_METODOS = (
    ('EFECTIVO', 'EFECTIVO'),
    ('TARJETA', 'TARJETA'),
    ('YAPE', 'YAPE'),
)

PAGO_ESTADOS = (
    ('PENDIENTE', 'PENDIENTE'),
    ('COMPLETADO', 'COMPLETADO'),
    ('RECHAZADO', 'RECHAZADO'),
)

DIAS_SEMANA = (
    ('Lunes', 'Lunes'),
    ('Martes', 'Martes'),
    ('Miércoles', 'Miércoles'),
    ('Jueves', 'Jueves'),
    ('Viernes', 'Viernes'),
    ('Sábado', 'Sábado'),
    ('Domingo', 'Domingo'),
)


@admin_only
def mesa_create_view(request):
    ctx = {'posted': None, 'mesa': None, 'estados': MESA_ESTADOS}
    if request.method == 'POST':
        try:
            numero_mesa = int((request.POST.get('numero_mesa') or '').strip())
            capacidad = int((request.POST.get('capacidad') or '').strip())
        except ValueError:
            messages.error(request, 'Número de mesa y capacidad deben ser números enteros válidos.')
            ctx['posted'] = request.POST
            return render(request, 'admin/mesa_form.html', ctx, status=400)
        estado = (request.POST.get('estado') or 'libre').strip()
        ubicacion = (request.POST.get('ubicacion') or '').strip() or None
        try:
            CrearMesaUseCase(_mesa_repository()).execute(
                numero_mesa, capacidad, estado=estado, ubicacion=ubicacion
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/mesa_form.html', ctx, status=400)
        messages.success(request, 'Mesa creada correctamente.')
        return redirect('admin_mesas')
    return render(request, 'admin/mesa_form.html', ctx)


@admin_only
def mesa_edit_view(request, pk):
    repo = _mesa_repository()
    try:
        mesa = ObtenerMesaUseCase(repo).execute(pk)
    except LookupError:
        raise Http404
    ctx = {'posted': None, 'mesa': mesa, 'estados': MESA_ESTADOS}
    if request.method == 'POST':
        try:
            numero_mesa = int((request.POST.get('numero_mesa') or '').strip())
            capacidad = int((request.POST.get('capacidad') or '').strip())
        except ValueError:
            messages.error(request, 'Número de mesa y capacidad deben ser números enteros válidos.')
            ctx['posted'] = request.POST
            return render(request, 'admin/mesa_form.html', ctx, status=400)
        estado = (request.POST.get('estado') or 'libre').strip()
        ubicacion = (request.POST.get('ubicacion') or '').strip() or None
        try:
            ActualizarMesaUseCase(repo).execute(
                pk, numero_mesa=numero_mesa, capacidad=capacidad, estado=estado, ubicacion=ubicacion
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/mesa_form.html', ctx, status=400)
        except LookupError:
            raise Http404
        messages.success(request, 'Mesa actualizada correctamente.')
        return redirect('admin_mesas')
    return render(request, 'admin/mesa_form.html', ctx)


@admin_only
def reserva_create_view(request):
    mesas = MesaModel.objects.order_by('numero_mesa')
    ctx = {
        'posted': None,
        'mesas': mesas,
        'estados': RESERVA_ESTADOS,
        'clientes': _clientes_queryset(),
    }
    if request.method == 'POST':
        mesa_raw = (request.POST.get('mesa_id') or '').strip()
        fecha_str = (request.POST.get('fecha') or '').strip()
        hora_str = (request.POST.get('hora') or '').strip()
        try:
            mesa_id = int(mesa_raw)
            nper = int((request.POST.get('numero_personas') or '').strip())
        except ValueError:
            messages.error(request, 'Selecciona una mesa válida y un número de personas correcto.')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        if not MesaModel.objects.filter(pk=mesa_id).exists():
            messages.error(request, 'La mesa seleccionada no existe.')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        try:
            d = date.fromisoformat(fecha_str)
        except ValueError:
            messages.error(request, 'Indica una fecha válida (AAAA-MM-DD).')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        hora_str = hora_str or '12:00'
        parts = hora_str.strip().split(':')
        try:
            h = int(parts[0])
            mi = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            messages.error(request, 'Indica la hora como HH:MM (ej. 20:30).')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        hora_display = f'{h:02d}:{mi:02d}'
        naive = datetime.combine(d, dt_time(h, mi))
        fecha_reserva = timezone.make_aware(naive, timezone.get_current_timezone())
        estado = (request.POST.get('estado') or 'PENDIENTE').strip()
        codigo = (request.POST.get('codigo_reserva') or '').strip() or None
        nombre_cliente = (request.POST.get('nombre_cliente') or '').strip() or None
        email_cliente = (request.POST.get('email_cliente') or '').strip() or None
        telefono_cliente = (request.POST.get('telefono_cliente') or '').strip() or None

        if nombre_cliente and any(c.isdigit() for c in nombre_cliente):
            messages.error(request, 'El nombre del cliente no puede contener números.')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        if email_cliente and ('@' not in email_cliente or '.' not in email_cliente.split('@')[-1]):
            messages.error(request, 'Indica un email válido.')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        if telefono_cliente and not all(c in '0123456789+-() ' for c in telefono_cliente):
            messages.error(request, 'El teléfono solo puede contener números, +, - y espacios.')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        if d < date.today():
            messages.error(request, 'La fecha de la reserva no puede ser en el pasado.')
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        comentarios = (request.POST.get('comentarios') or '').strip() or None
        user_id = _optional_int(request.POST.get('user_id'))

        reserva_data = {
            'mesa_id': mesa_id,
            'fecha_reserva': fecha_reserva,
            'hora': hora_display,
            'numero_personas': nper,
            'estado': estado,
            'codigo_reserva': codigo,
            'nombre_cliente': nombre_cliente,
            'email_cliente': email_cliente,
            'telefono_cliente': telefono_cliente,
            'comentarios': comentarios,
            'user_id': user_id,
        }
        try:
            CrearReservaUseCase(_reserva_repository()).execute(reserva_data)
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/reserva_form.html', ctx, status=400)
        messages.success(request, 'Reserva creada correctamente.')
        return redirect('admin_reservas')
    return render(request, 'admin/reserva_form.html', ctx)


@admin_only
def pedido_edit_view(request, pk):
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise Http404
    pedido = PedidoModel.objects.filter(pk=pk).select_related('user', 'empleado_asignado').first()
    if not pedido:
        raise Http404

    if request.method == 'POST':
        cliente_nombre = (request.POST.get('cliente_nombre') or '').strip()
        total_raw = (request.POST.get('total') or '').strip()
        estado = (request.POST.get('estado') or '').strip().upper()
        numero_mesa = (request.POST.get('numero_mesa') or '').strip() or None
        comentarios = (request.POST.get('comentarios') or '').strip() or None

        if any(c.isdigit() for c in cliente_nombre):
            messages.error(request, 'El nombre del cliente no puede contener números.')
            return render(request, 'admin/pedido_edit_form.html', {'pedido': pedido, 'estados': PEDIDO_ESTADOS}, status=400)
        if numero_mesa and not numero_mesa.isdigit():
            messages.error(request, 'El número de mesa solo puede contener dígitos.')
            return render(request, 'admin/pedido_edit_form.html', {'pedido': pedido, 'estados': PEDIDO_ESTADOS}, status=400)
        try:
            total = float(total_raw.replace(',', '.'))
            if total < 0:
                raise ValueError
        except ValueError:
            messages.error(request, 'El total debe ser un número válido mayor o igual a 0.')
            return render(request, 'admin/pedido_edit_form.html', {'pedido': pedido, 'estados': PEDIDO_ESTADOS}, status=400)

        try:
            ActualizarPedidoUseCase(_pedido_repository()).execute(pk, {
                'cliente_nombre': cliente_nombre,
                'total': total,
                'estado': estado,
                'numero_mesa': numero_mesa,
                'comentarios': comentarios,
            })
        except LookupError:
            raise Http404
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, 'admin/pedido_edit_form.html', {'pedido': pedido, 'estados': PEDIDO_ESTADOS}, status=400)

        messages.success(request, f'Pedido #{pk} actualizado correctamente.')
        return redirect('admin_pedidos')

    return render(request, 'admin/pedido_edit_form.html', {'pedido': pedido, 'estados': PEDIDO_ESTADOS})


@admin_only
def pedido_create_view(request):
    reservas = ReservaModel.objects.select_related('mesa').order_by('-fecha_reserva')[:300]
    ctx = {
        'posted': None,
        'estados': PEDIDO_ESTADOS,
        'empleados': _empleados_queryset(),
        'clientes': _clientes_queryset(),
        'reservas': reservas,
    }
    if request.method == 'POST':
        cliente_nombre = (request.POST.get('cliente_nombre') or '').strip()
        total_raw = (request.POST.get('total') or '').strip()
        estado = (request.POST.get('estado') or 'PENDIENTE').strip()
        numero_mesa = (request.POST.get('numero_mesa') or '').strip() or None
        comentarios = (request.POST.get('comentarios') or '').strip() or None
        user_id = _optional_int(request.POST.get('user_id'))
        reserva_id = _optional_int(request.POST.get('reserva_id'))
        empleado_id = _optional_int(request.POST.get('empleado_id'))
        if any(c.isdigit() for c in cliente_nombre):
            messages.error(request, 'El nombre del cliente no puede contener números.')
            ctx['posted'] = request.POST
            return render(request, 'admin/pedido_form.html', ctx, status=400)
        if numero_mesa and not numero_mesa.isdigit():
            messages.error(request, 'El número de mesa solo puede contener dígitos.')
            ctx['posted'] = request.POST
            return render(request, 'admin/pedido_form.html', ctx, status=400)
        try:
            total = float(total_raw.replace(',', '.'))
            if total < 0:
                raise ValueError
        except ValueError:
            messages.error(request, 'El total debe ser un número válido mayor o igual a 0.')
            ctx['posted'] = request.POST
            return render(request, 'admin/pedido_form.html', ctx, status=400)
        pedido_data = {
            'total': total,
            'cliente_nombre': cliente_nombre,
            'estado': estado,
            'numero_mesa': numero_mesa,
            'user_id': user_id,
            'reserva_id': reserva_id,
            'empleado_id': empleado_id,
            'comentarios': comentarios,
        }
        try:
            CrearPedidoUseCase(_pedido_repository()).execute(pedido_data)
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/pedido_form.html', ctx, status=400)
        messages.success(request, 'Pedido creado correctamente.')
        return redirect('admin_pedidos')
    return render(request, 'admin/pedido_form.html', ctx)


@admin_only
def pago_create_view(request):
    pedidos = PedidoModel.objects.order_by('-fecha_creacion')[:400]
    ctx = {
        'posted': None,
        'pedidos': pedidos,
        'metodos': PAGO_METODOS,
        'estados': PAGO_ESTADOS,
        'clientes': _clientes_queryset(),
    }
    if request.method == 'POST':
        pedido_id = _optional_int(request.POST.get('pedido_id'))
        if not pedido_id or not PedidoModel.objects.filter(pk=pedido_id).exists():
            messages.error(request, 'Selecciona un pedido válido.')
            ctx['posted'] = request.POST
            return render(request, 'admin/pago_form.html', ctx, status=400)
        metodo_raw = (request.POST.get('metodo_pago') or '').strip()
        if not metodo_raw:
            messages.error(request, 'Indica el método de pago.')
            ctx['posted'] = request.POST
            return render(request, 'admin/pago_form.html', ctx, status=400)
        metodo_pago = metodo_raw.upper()
        monto_raw = (request.POST.get('monto_total') or '').strip()
        try:
            monto_total = float(monto_raw.replace(',', '.'))
        except ValueError:
            messages.error(request, 'El monto debe ser un número válido.')
            ctx['posted'] = request.POST
            return render(request, 'admin/pago_form.html', ctx, status=400)
        estado = (request.POST.get('estado') or 'PENDIENTE').strip().upper()
        user_id = _optional_int(request.POST.get('user_id'))
        fp_raw = (request.POST.get('fecha_pago') or '').strip()
        fecha_pago = None
        if fp_raw:
            try:
                fecha_pago = date.fromisoformat(fp_raw)
            except ValueError:
                messages.error(request, 'La fecha de pago debe ser AAAA-MM-DD.')
                ctx['posted'] = request.POST
                return render(request, 'admin/pago_form.html', ctx, status=400)
        try:
            CrearPagoUseCase(_pago_repository()).execute(
                pedido_id,
                metodo_pago,
                monto_total,
                estado=estado,
                user_id=user_id,
                fecha_pago=fecha_pago,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/pago_form.html', ctx, status=400)
        messages.success(request, 'Pago registrado correctamente.')
        return redirect('admin_pagos')
    return render(request, 'admin/pago_form.html', ctx)


@admin_only
def horario_delete_view(request, pk):
    try:
        horario = HorarioModel.objects.select_related('user').get(pk=pk)
    except HorarioModel.DoesNotExist:
        raise Http404
    if request.method == 'POST':
        horario.delete()
        messages.success(request, 'Horario eliminado correctamente.')
        return redirect('admin_horarios')
    return render(request, 'admin/horario_confirm_delete.html', {'horario': horario})


@admin_only
def horario_edit_view(request, pk):
    try:
        horario = HorarioModel.objects.select_related('user').get(pk=pk)
    except HorarioModel.DoesNotExist:
        raise Http404

    ctx = {'horario': horario, 'empleados': _empleados_queryset(), 'dias': DIAS_SEMANA}

    if request.method == 'POST':
        import re
        user_id = _optional_int(request.POST.get('user_id'))
        dia_semana = (request.POST.get('dia_semana') or '').strip()
        hora_inicio = (request.POST.get('hora_inicio') or '').strip()
        hora_fin = (request.POST.get('hora_fin') or '').strip()

        if not user_id or not UserModel.objects.filter(pk=user_id).exists():
            messages.error(request, 'Selecciona un empleado válido.')
            return render(request, 'admin/horario_edit_form.html', ctx, status=400)
        _time_re = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
        if not _time_re.match(hora_inicio) or not _time_re.match(hora_fin):
            messages.error(request, 'Las horas deben tener formato HH:MM.')
            return render(request, 'admin/horario_edit_form.html', ctx, status=400)
        if hora_fin <= hora_inicio:
            messages.error(request, 'La hora de fin debe ser mayor que la hora de inicio.')
            return render(request, 'admin/horario_edit_form.html', ctx, status=400)

        HorarioModel.objects.filter(pk=pk).update(
            user_id=user_id,
            dia_semana=dia_semana,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        )
        from users.infrastructure.models.notificacion_model import NotificacionModel
        NotificacionModel.objects.create(
            usuario_id=user_id,
            mensaje=f'Tu horario del {dia_semana} ha sido modificado: {hora_inicio} – {hora_fin}.',
        )
        messages.success(request, 'Horario actualizado correctamente.')
        return redirect('admin_horarios')

    return render(request, 'admin/horario_edit_form.html', ctx)


@admin_only
def horario_create_view(request):
    ctx = {'posted': None, 'empleados': _empleados_queryset(), 'dias': DIAS_SEMANA}
    if request.method == 'POST':
        user_id = _optional_int(request.POST.get('user_id'))
        dia_semana = (request.POST.get('dia_semana') or '').strip()
        hora_inicio = (request.POST.get('hora_inicio') or '').strip()
        hora_fin = (request.POST.get('hora_fin') or '').strip()
        if not user_id or not UserModel.objects.filter(pk=user_id).exists():
            messages.error(request, 'Selecciona un empleado válido.')
            ctx['posted'] = request.POST
            return render(request, 'admin/horario_form.html', ctx, status=400)
        import re
        _time_re = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
        if not _time_re.match(hora_inicio):
            messages.error(request, 'La hora de inicio debe tener formato HH:MM (ej. 08:00).')
            ctx['posted'] = request.POST
            return render(request, 'admin/horario_form.html', ctx, status=400)
        if not _time_re.match(hora_fin):
            messages.error(request, 'La hora de fin debe tener formato HH:MM (ej. 17:00).')
            ctx['posted'] = request.POST
            return render(request, 'admin/horario_form.html', ctx, status=400)
        if hora_fin <= hora_inicio:
            messages.error(request, 'La hora de fin debe ser mayor que la hora de inicio.')
            ctx['posted'] = request.POST
            return render(request, 'admin/horario_form.html', ctx, status=400)
        try:
            CrearHorarioUseCase(_horario_repository()).execute(
                user_id, dia_semana, hora_inicio, hora_fin
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/horario_form.html', ctx, status=400)
        messages.success(request, 'Horario creado correctamente.')
        return redirect('admin_horarios')
    return render(request, 'admin/horario_form.html', ctx)


@admin_only
def enviar_correo_masivo_view(request):
    from users.infrastructure.models import NoticiaModel, PromocionModel
    noticias = NoticiaModel.objects.order_by('-fecha_publicacion')
    promociones = PromocionModel.objects.order_by('-fecha_inicio')

    if request.method == 'POST':
        tipo = (request.POST.get('tipo') or '').strip()
        subject = (request.POST.get('subject') or '').strip()
        noticias_ids = request.POST.getlist('noticias_ids')
        promociones_ids = request.POST.getlist('promociones_ids')

        incluir_noticias = tipo in ('noticias', 'ambas')
        incluir_promociones = tipo in ('promociones', 'ambas')

        sel_noticias = NoticiaModel.objects.filter(pk__in=noticias_ids) if incluir_noticias and noticias_ids else (
            NoticiaModel.objects.order_by('-fecha_publicacion') if incluir_noticias else []
        )
        sel_promociones = PromocionModel.objects.filter(pk__in=promociones_ids) if incluir_promociones and promociones_ids else (
            PromocionModel.objects.order_by('-fecha_inicio') if incluir_promociones else []
        )

        if not sel_noticias and not sel_promociones:
            messages.error(request, 'Selecciona al menos una noticia o promoción.')
            return render(request, 'admin/correo_masivo_form.html', {'noticias': noticias, 'promociones': promociones})

        # Construir asunto automático
        if not subject:
            partes = []
            if sel_noticias: partes.append('Noticias')
            if sel_promociones: partes.append('Promociones')
            subject = f"{'  y '.join(partes)} de Olla y Sazón 🍽️"

        # Construir cuerpo HTML profesional
        def abs_img(url):
            """Convierte ruta relativa /media/... en URL absoluta accesible desde internet."""
            if not url:
                return ''
            if url.startswith('http'):
                return url
            return request.build_absolute_uri(url)

        bloques = []
        if sel_noticias:
            bloques.append(
                '<tr><td style="padding:8px 32px 4px">'
                '<p style="margin:0;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#b8860b">&#128240; Noticias del restaurante</p>'
                '</td></tr>'
            )
            for n in sel_noticias:
                img_url = abs_img(n.imagen)
                img = (f'<tr><td style="padding:0 32px 12px">'
                       f'<img src="{img_url}" style="width:100%;max-width:536px;border-radius:8px;display:block">'
                       f'</td></tr>') if img_url else ''
                bloques.append(
                    f'{img}'
                    f'<tr><td style="padding:0 32px 24px;border-bottom:1px solid #f0e6c8">'
                    f'<h3 style="margin:0 0 8px;font-size:18px;color:#1a1a1a;font-family:Georgia,serif">{n.titulo}</h3>'
                    f'<p style="margin:0;font-size:14px;color:#555;line-height:1.6">{n.contenido}</p>'
                    f'</td></tr>'
                )
        if sel_promociones:
            bloques.append(
                '<tr><td style="padding:24px 32px 4px">'
                '<p style="margin:0;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#b8860b">&#127991; Promociones especiales</p>'
                '</td></tr>'
            )
            for p in sel_promociones:
                img_url = abs_img(p.imagen_url)
                img = (f'<tr><td style="padding:0 32px 12px">'
                       f'<img src="{img_url}" style="width:100%;max-width:536px;border-radius:8px;display:block">'
                       f'</td></tr>') if img_url else ''
                desc = f'<p style="margin:6px 0 0;font-size:14px;color:#555;line-height:1.6">{p.descripcion}</p>' if p.descripcion else ''
                bloques.append(
                    f'{img}'
                    f'<tr><td style="padding:0 32px 24px;border-bottom:1px solid #f0e6c8">'
                    f'<h3 style="margin:0 0 6px;font-size:18px;color:#1a1a1a;font-family:Georgia,serif">{p.titulo}</h3>'
                    f'<span style="display:inline-block;background:#ffd700;color:#1a1a1a;font-weight:700;font-size:13px;padding:4px 12px;border-radius:20px;margin-bottom:4px">{p.descuento}% de descuento</span>'
                    f'<p style="margin:4px 0 0;font-size:12px;color:#888">Válido del {p.fecha_inicio} al {p.fecha_fin}</p>'
                    f'{desc}'
                    f'</td></tr>'
                )

        html_body = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body style="margin:0;padding:0;background:#f5f0e8">'
            '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;padding:32px 0">'
            '<tr><td align="center">'
            '<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10)">'
            # Header
            '<tr><td style="background:#1a1a1a;padding:28px 32px;text-align:center">'
            '<h1 style="margin:0;font-family:Georgia,serif;font-size:28px;color:#ffd700;letter-spacing:1px">&#127869;&#65039; Olla y Saz&#243;n</h1>'
            '<p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.6)">Sabor que enamora</p>'
            '</td></tr>'
            # Divider
            '<tr><td style="background:#ffd700;height:4px"></td></tr>'
            # Content
            '<tr><td style="padding:28px 32px 8px">'
            '<p style="margin:0;font-size:15px;color:#333;line-height:1.6">Hola, te compartimos las últimas novedades de nuestro restaurante. &#128522;</p>'
            '</td></tr>'
            + ''.join(bloques) +
            # Footer
            '<tr><td style="background:#1a1a1a;padding:20px 32px;text-align:center">'
            '<p style="margin:0 0 8px;font-size:12px;color:rgba(255,255,255,0.5)">&copy; Restaurante Olla y Saz&#243;n &nbsp;|&nbsp; Gracias por ser parte de nuestra familia</p>'
            '<p style="margin:0;font-size:11px"><a href="{unsubscribe}" style="color:#ffd700;text-decoration:underline">Cancelar suscripci&#243;n</a></p>'
            '</td></tr>'
            '</table>'
            '</td></tr></table>'
            '</body></html>'
        )

        try:
            from users.utils.sendpulse import enviar_promocion_a_clientes
            enviar_promocion_a_clientes(subject=subject, html_body=html_body)
            messages.success(request, 'Correo masivo enviado correctamente a todos los clientes activos.')
        except RuntimeError as exc:
            msg = str(exc)
            if 'Sender is not valid' in msg:
                messages.error(request, 'El remitente no está verificado en SendPulse. Ve a app.sendpulse.com → Email → Senders y verifica oscar14leguizamon@gmail.com')
            elif 'auth error' in msg:
                messages.error(request, f'Error de autenticación con SendPulse: {msg}')
            else:
                messages.error(request, f'Error al enviar: {msg}')
        except Exception as exc:
            messages.error(request, f'Error inesperado: {exc}')
        return redirect('admin_correo_masivo')

    return render(request, 'admin/correo_masivo_form.html', {'noticias': noticias, 'promociones': promociones})


@admin_only
def noticia_admin_create_view(request):
    ctx = {'posted': None}
    if request.method == 'POST':
        titulo = (request.POST.get('titulo') or '').strip()
        contenido = (request.POST.get('contenido') or '').strip()
        imagen_url_manual = (request.POST.get('imagen_url') or '').strip()
        fp_raw = (request.POST.get('fecha_publicacion') or '').strip()
        if not titulo or not contenido:
            messages.error(request, 'Título y contenido son obligatorios.')
            ctx['posted'] = request.POST
            return render(request, 'admin/noticia_admin_form.html', ctx, status=400)
        fecha_publicacion = None
        if fp_raw:
            try:
                fecha_publicacion = date.fromisoformat(fp_raw)
            except ValueError:
                messages.error(request, 'La fecha de publicación debe ser AAAA-MM-DD.')
                ctx['posted'] = request.POST
                return render(request, 'admin/noticia_admin_form.html', ctx, status=400)
        imagen_url = imagen_url_manual or None
        if request.FILES.get('imagen'):
            try:
                imagen_url = _save_noticia_image_upload(request.FILES['imagen'])
            except ValueError as exc:
                messages.error(request, str(exc))
                ctx['posted'] = request.POST
                return render(request, 'admin/noticia_admin_form.html', ctx, status=400)
        try:
            CrearNoticiaUseCase(_noticia_repository()).execute(
                titulo, contenido, imagen=imagen_url, fecha_publicacion=fecha_publicacion
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
            return render(request, 'admin/noticia_admin_form.html', ctx, status=400)
        messages.success(request, 'Noticia publicada correctamente.')
        return redirect('noticias')
    return render(request, 'admin/noticia_admin_form.html', ctx)




@admin_only
def solicitudes_turno_list_view(request):
    solicitudes = SolicitudCambioTurnoModel.objects.select_related('empleado', 'horario').order_by('-fecha_creacion')
    return render(request, 'admin/solicitudes_turno_list.html', {'solicitudes': solicitudes})


@admin_only
def solicitud_turno_responder_view(request, pk):
    from django.shortcuts import get_object_or_404
    solicitud = get_object_or_404(SolicitudCambioTurnoModel.objects.select_related('empleado'), pk=pk)

    if request.method == 'POST':
        accion = (request.POST.get('accion') or '').strip().upper()
        respuesta = (request.POST.get('respuesta_admin') or '').strip()
        if accion not in ('APROBADA', 'RECHAZADA'):
            messages.error(request, 'Acción no válida.')
            return redirect('admin_solicitudes_turno')
        if accion == 'RECHAZADA' and not respuesta:
            messages.error(request, 'Debes indicar el motivo del rechazo.')
            return render(request, 'admin/solicitud_turno_responder.html', {'solicitud': solicitud})
        SolicitudCambioTurnoModel.objects.filter(pk=pk).update(
            estado=accion,
            respuesta_admin=respuesta,
        )
        from users.infrastructure.models.notificacion_model import NotificacionModel
        estado_label = 'aprobada' if accion == 'APROBADA' else 'rechazada'
        msg_notif = f'Tu solicitud de cambio de turno fue {estado_label}.'
        if respuesta:
            msg_notif += f' Nota del admin: {respuesta}'
        NotificacionModel.objects.create(usuario=solicitud.empleado, mensaje=msg_notif)
        messages.success(request, f'Solicitud {accion.lower()} correctamente.')
        return redirect('admin_solicitudes_turno')

    return render(request, 'admin/solicitud_turno_responder.html', {'solicitud': solicitud})
