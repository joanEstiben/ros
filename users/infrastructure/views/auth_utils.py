from django.urls import reverse


def post_login_redirect_url(user):
    """Destino tras login según rol."""
    # Superusuario sin rol -> dashboard del proyecto
    if user.is_superuser or user.is_staff:
        return reverse('admin_dashboard')

    r = getattr(user, 'rol', None)
    nombre = (r.nombre or '').strip().upper() if r else ''
    if nombre in ('ADMIN', 'ADMINISTRADOR'):
        return reverse('admin_dashboard')
    if nombre == 'CLIENTE':
        return reverse('mi_perfil')
    if nombre == 'EMPLEADO':
        return reverse('pedidos_asignados')
    return reverse('login')
