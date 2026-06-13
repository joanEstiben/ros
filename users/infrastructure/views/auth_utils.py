from django.urls import reverse as django_reverse


def post_login_redirect_url(user):
    """Destino tras login según rol."""
    # Superusuario sin rol -> dashboard del proyecto
    if user.is_superuser or user.is_staff:
        return django_reverse('admin_dashboard')

    r = getattr(user, 'rol', None)
    nombre = (r.nombre or '').strip().upper() if r else ''

    if nombre in ('ADMIN', 'ADMINISTRADOR'):
        return django_reverse('admin_dashboard')
    if nombre == 'CLIENTE':
        return django_reverse('mi_perfil')
    if nombre == 'EMPLEADO':
        return django_reverse('pedidos_asignados')

    return django_reverse('login')