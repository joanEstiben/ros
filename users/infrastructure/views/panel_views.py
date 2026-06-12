from __future__ import annotations

import json
import time

from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from users.application.application.use_cases.pedido_usecase import CambiarEstadoPedidoUseCase
from users.infrastructure.models import (
    DetallePedidoModel,
    InventarioModel,
    MesaModel,
    NoticiaModel,
    PagoModel,
    PedidoModel,
    ProductoModel,
    PromocionModel,
    ReservaModel,
    UserModel,
)
from users.infrastructure.models.horario_model import HorarioModel
from users.infrastructure.models.insumo_model import InsumoModel
from users.infrastructure.models.solicitud_cambio_turno_model import SolicitudCambioTurnoModel
from users.infrastructure.models.notificacion_model import NotificacionModel
from users.infrastructure.repositories.pedido_repository_impl import PedidoRepositoryImpl
from users.forms import SolicitudCambioTurnoForm


def _rol_upper(user):
    r = getattr(user, 'rol', None)
    raw = (r.nombre or '').strip().upper() if r else ''
    if raw in ('ADMIN', 'ADMINISTRADOR'):
        return 'ADMINISTRADOR'
    return raw


def _coerce_orm_day(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return timezone.localtime(val).date() if timezone.is_aware(val) else val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return date.fromisoformat(val.strip()[:10])
    return val


def _pedidos_cliente_qs(user):
    return PedidoModel.objects.filter(user=user).exclude(
        Q(estado__iexact='CANCELADO') | Q(estado__iexact='CANCELADA')
    )


@login_required(login_url='/login/')
def mi_perfil_view(request):
    rol = _rol_upper(request.user)
    if rol != 'CLIENTE':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        if rol == 'ADMINISTRADOR':
            return redirect('admin_dashboard')
        if rol == 'EMPLEADO':
            return redirect('pedidos_asignados')
        return redirect('login')

    user = request.user
    pedidos_qs = _pedidos_cliente_qs(user)
    total_gastado = float(pedidos_qs.aggregate(s=Sum('total')).get('s') or 0.0)
    pedidos_count = pedidos_qs.count()

    fav = (
        DetallePedidoModel.objects.filter(pedido__in=pedidos_qs)
        .values('producto_id', 'producto__nombre')
        .annotate(total_qty=Sum('cantidad'))
        .order_by('-total_qty')
        .first()
    )
    plato_favorito = None
    favorito_cantidad = 0
    if fav:
        plato_favorito = fav.get('producto__nombre')
        favorito_cantidad = int(fav.get('total_qty') or 0)

    ultimos_pedidos = list(
        pedidos_qs.select_related('empleado_asignado').order_by('-fecha_creacion')[:8]
    )

    reservas_qs = ReservaModel.objects.filter(
        Q(user=user) | Q(email_cliente__iexact=user.email)
    ).order_by('-fecha_reserva')
    reservas_count = reservas_qs.count()
    ultimas_reservas = list(reservas_qs[:5])

    hoy = timezone.localdate()
    promociones_activas = list(
        PromocionModel.objects.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).order_by('-fecha_inicio')
    )

    return render(
        request,
        'cliente/perfil_panel.html',
        {
            'total_gastado': total_gastado,
            'pedidos_count': pedidos_count,
            'plato_favorito': plato_favorito,
            'favorito_cantidad': favorito_cantidad,
            'ultimos_pedidos': ultimos_pedidos,
            'reservas_count': reservas_count,
            'ultimas_reservas': ultimas_reservas,
            'promociones_activas': promociones_activas,
        },
    )


@login_required(login_url='/login/')
def mi_horario_view(request):
    rol = _rol_upper(request.user)
    if rol != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        if rol == 'ADMINISTRADOR':
            return redirect('admin_dashboard')
        if rol == 'CLIENTE':
            return redirect('mi_perfil')
        return redirect('login')

    qs = HorarioModel.objects.filter(user=request.user).select_related('user')
    horarios = list(qs)

    day_order = {
        'LUNES': 0, 'MARTES': 1, 'MIERCOLES': 2, 'MIÉRCOLES': 2,
        'JUEVES': 3, 'VIERNES': 4, 'SABADO': 5, 'SÁBADO': 5, 'DOMINGO': 6,
    }

    def _sort_key(h):
        dia = (h.dia_semana or '').strip().upper()
        return (day_order.get(dia, 99), h.hora_inicio or '', h.hora_fin or '')

    horarios.sort(key=_sort_key)

    dias_horarios = []
    seen = set()
    for h in horarios:
        dia = (h.dia_semana or '').strip()
        if dia not in seen:
            seen.add(dia)
            dias_horarios.append({'dia': dia, 'intervalos': []})
        dias_horarios[-1]['intervalos'].append(h)

    total_turnos = len(horarios)
    dias_count = len(dias_horarios)
    proxima_entrada = min((h.hora_inicio for h in horarios if h.hora_inicio), default=None)

    # Horarios modificados en las últimas 24h
    hace_24h = timezone.now() - timedelta(hours=24)
    recientes = HorarioModel.objects.filter(
        user=request.user,
        fecha_actualizacion__gte=hace_24h,
    ).values_list('dia_semana', flat=True)
    dias_recientes = list(recientes)

    return render(
        request,
        'empleado/mi_horario_panel.html',
        {
            'horarios': horarios,
            'dias_horarios': dias_horarios,
            'total_turnos': total_turnos,
            'dias_count': dias_count,
            'proxima_entrada': proxima_entrada,
            'dias_recientes': dias_recientes,
        },
    )


@login_required(login_url='/login/')
def reserva_detalle_mesero_view(request, pk):
    if _rol_upper(request.user) != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        return redirect('admin_dashboard') if _rol_upper(request.user) == 'ADMINISTRADOR' else redirect('mi_perfil')

    reserva = get_object_or_404(ReservaModel.objects.select_related('mesa', 'user'), pk=pk)

    TRANSICIONES = {
        'PENDIENTE':  ['COMPLETADA', 'NO_SE_PRESENTO'],
        'CONFIRMADA': ['COMPLETADA', 'NO_SE_PRESENTO'],
        'COMPLETADA': [],
        'NO_SE_PRESENTO': [],
        'CANCELADA': [],
    }

    if request.method == 'POST':
        nuevo_estado = (request.POST.get('nuevo_estado') or '').strip().upper()
        permitidos = TRANSICIONES.get((reserva.estado or '').upper(), [])
        if nuevo_estado not in permitidos:
            messages.error(request, 'Transición de estado no permitida.')
            return redirect('reserva_detalle_mesero', pk=pk)
        ReservaModel.objects.filter(pk=pk).update(estado=nuevo_estado)
        messages.success(request, f'Reserva actualizada a «{nuevo_estado}».')
        return redirect('reservas_hoy_mesero')

    permitidos = TRANSICIONES.get((reserva.estado or '').upper(), [])
    return render(request, 'empleado/reserva_detalle.html', {
        'reserva': reserva,
        'permitidos': permitidos,
    })


@login_required(login_url='/login/')
def reservas_hoy_mesero_view(request):
    if _rol_upper(request.user) != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        return redirect('admin_dashboard') if _rol_upper(request.user) == 'ADMINISTRADOR' else redirect('mi_perfil')

    tz = timezone.get_current_timezone()
    fecha_str = (request.GET.get('fecha') or '').strip()
    try:
        today = date.fromisoformat(fecha_str)
    except ValueError:
        today = timezone.localdate()

    inicio = timezone.datetime.combine(today, timezone.datetime.min.time()).replace(tzinfo=tz)
    fin = timezone.datetime.combine(today, timezone.datetime.max.time()).replace(tzinfo=tz)
    reservas = (
        ReservaModel.objects.select_related('mesa', 'user')
        .filter(fecha_reserva__gte=inicio, fecha_reserva__lte=fin)
        .exclude(estado__in=['CANCELADA', 'CANCELADO'])
        .order_by('hora')
    )
    return render(request, 'empleado/reservas_hoy.html', {
        'reservas': reservas,
        'hoy': today,
    })


@login_required(login_url='/login/')
def pedidos_asignados_view(request):
    rol = _rol_upper(request.user)
    if rol != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        if rol == 'ADMINISTRADOR':
            return redirect('admin_dashboard')
        if rol == 'CLIENTE':
            return redirect('mi_perfil')
        return redirect('login')

    repo = PedidoRepositoryImpl()
    qs = (
        PedidoModel.objects.select_related('user', 'empleado_asignado')
        .prefetch_related('detalles__producto')
        .filter(empleado_asignado=request.user)
        .order_by('-fecha_creacion')
    )

    estados = ['PENDIENTE', 'EN_PREPARACION', 'LISTO', 'ENTREGADO', 'CANCELADO']
    pedidos_counts = {e: qs.filter(estado=e).count() for e in estados}

    transiciones = {
        'PENDIENTE': ['EN_PREPARACION', 'CANCELADO'],
        'EN_PREPARACION': ['LISTO', 'CANCELADO'],
        'LISTO': ['ENTREGADO', 'CANCELADO'],
        'ENTREGADO': [],
        'CANCELADO': [],
    }

    pedidos = list(qs)
    for p in pedidos:
        p.allowed_next = transiciones.get(getattr(p, 'estado', None), [])

    if request.method == 'POST':
        pedido_id = request.POST.get('pedido_id')
        nuevo_estado = (request.POST.get('nuevo_estado') or '').strip().upper()
        if not pedido_id or not nuevo_estado:
            messages.error(request, 'Datos del formulario inválidos.')
            return redirect('pedidos_asignados')
        try:
            pedido_id_int = int(pedido_id)
        except ValueError:
            messages.error(request, 'ID de pedido inválido.')
            return redirect('pedidos_asignados')

        pedido = (
            PedidoModel.objects.filter(pk=pedido_id_int, empleado_asignado=request.user)
            .select_related('user')
            .first()
        )
        if not pedido:
            messages.error(request, 'Ese pedido no te pertenece.')
            return redirect('pedidos_asignados')

        allowed = transiciones.get(pedido.estado, [])
        if nuevo_estado not in allowed:
            messages.error(request, 'No puedes cambiar el pedido a ese estado desde su estado actual.')
            return redirect('pedidos_asignados')

        try:
            CambiarEstadoPedidoUseCase(repo).execute(pedido_id_int, nuevo_estado)
            messages.success(request, f'Pedido actualizado a «{nuevo_estado}».')
        except Exception as exc:
            messages.error(request, f'No se pudo actualizar el pedido: {exc}')

        return redirect('pedidos_asignados')

    return render(
        request,
        'empleado/pedidos_asignados_panel.html',
        {
            'pedidos': pedidos,
            'pedidos_counts': pedidos_counts,
            'transiciones': transiciones,
        },
    )


def home_redirect_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    rol = _rol_upper(request.user)
    if rol == 'ADMINISTRADOR':
        return redirect('admin_dashboard')
    if rol == 'EMPLEADO':
        return redirect('pedidos_asignados')
    if rol == 'CLIENTE':
        return redirect('mi_perfil')
    # Superusuario sin rol asignado -> dashboard Django admin
    if request.user.is_superuser:
        return redirect('/admin/')
    return redirect('login')


@login_required(login_url='/login/')
def admin_dashboard_view(request):
    rol = _rol_upper(request.user)
    if rol != 'ADMINISTRADOR':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        if rol == 'EMPLEADO':
            return redirect('pedidos_asignados')
        if rol == 'CLIENTE':
            return redirect('mi_perfil')
        return redirect('login')

    today = timezone.localdate()
    start = today - timedelta(days=6)
    tz = timezone.get_current_timezone()

    pedidos_by_day = {}
    for row in (
        PedidoModel.objects.filter(fecha_creacion__date__gte=start)
        .annotate(day=TruncDate("fecha_creacion", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
        .order_by("day")
    ):
        d = _coerce_orm_day(row["day"])
        if d is not None:
            pedidos_by_day[d] = row["c"]

    reservas_by_day = {}
    for row in (
        ReservaModel.objects.filter(fecha_creacion__date__gte=start)
        .annotate(day=TruncDate("fecha_creacion", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
        .order_by("day")
    ):
        d = _coerce_orm_day(row["day"])
        if d is not None:
            reservas_by_day[d] = row["c"]

    ingresos_by_day = {}
    for row in (
        PagoModel.objects.filter(fecha_creacion__date__gte=start)
        .annotate(day=TruncDate("fecha_creacion", tzinfo=tz))
        .values("day")
        .annotate(s=Sum("monto_total"))
        .order_by("day")
    ):
        d = _coerce_orm_day(row["day"])
        if d is not None:
            ingresos_by_day[d] = float(row["s"] or 0.0)

    labels = [(start + timedelta(days=i)) for i in range(7)]
    chart_labels = [d.strftime("%d/%m") for d in labels]
    chart_pedidos = [int(pedidos_by_day.get(d, 0)) for d in labels]
    chart_reservas = [int(reservas_by_day.get(d, 0)) for d in labels]
    chart_ingresos = [float(ingresos_by_day.get(d, 0.0)) for d in labels]

    alertas_inventario = list(
        InventarioModel.objects.select_related('producto')
        .filter(cantidad_disponible__lte=models.F('cantidad_minima'))
        .order_by('cantidad_disponible')
    )
    alertas_insumos = list(
        InsumoModel.objects.filter(stock_actual__lte=models.F('stock_minimo'))
        .order_by('stock_actual')
    )

    ingresos_total = float(PagoModel.objects.aggregate(s=Sum("monto_total")).get("s") or 0.0)
    ingresos_mes = float(
        PagoModel.objects.filter(
            fecha_creacion__year=today.year,
            fecha_creacion__month=today.month,
        ).aggregate(s=Sum("monto_total")).get("s") or 0.0
    )
    ingresos_hoy = float(
        PagoModel.objects.filter(fecha_creacion__date=today).aggregate(s=Sum("monto_total")).get("s") or 0.0
    )

    pedidos_hoy = PedidoModel.objects.filter(fecha_creacion__date=today).count()
    reservas_hoy = ReservaModel.objects.filter(fecha_creacion__date=today).count()
    pedidos_pendientes = PedidoModel.objects.filter(estado="PENDIENTE").count()
    pagos_pendientes = PagoModel.objects.filter(estado="PENDIENTE").count()
    mesas_total = MesaModel.objects.count()
    mesas_libres = MesaModel.objects.filter(estado="libre").count()
    empleados_count = UserModel.objects.filter(activo=True, rol__nombre__iexact="EMPLEADO").count()
    empleados_preview = list(
        UserModel.objects.filter(activo=True, rol__nombre__iexact="EMPLEADO")
        .select_related("rol")
        .order_by("nombre", "apellido")[:10]
    )

    kpi = {
        "usuarios": UserModel.objects.count(),
        "empleados": empleados_count,
        "productos": ProductoModel.objects.count(),
        "noticias": NoticiaModel.objects.count(),
        "pedidos": PedidoModel.objects.count(),
        "reservas": ReservaModel.objects.count(),
        "ingresos_total": ingresos_total,
        "ingresos_mes": ingresos_mes,
        "ingresos_hoy": ingresos_hoy,
        "pedidos_hoy": pedidos_hoy,
        "reservas_hoy": reservas_hoy,
        "pedidos_pendientes": pedidos_pendientes,
        "pagos_pendientes": pagos_pendientes,
        "mesas_total": mesas_total,
        "mesas_libres": mesas_libres,
    }

    chart_data = {
        "labels": chart_labels,
        "pedidos": chart_pedidos,
        "reservas": chart_reservas,
        "ingresos": chart_ingresos,
    }

    ultimos_pedidos = list(
        PedidoModel.objects.select_related("user", "empleado_asignado").order_by("-fecha_creacion")[:5]
    )
    ultimas_reservas = list(
        ReservaModel.objects.select_related("mesa", "user").order_by("-fecha_creacion")[:5]
    )

    return render(
        request,
        "admin/dashboard.html",
        {
            "kpi": kpi,
            "ultimos_pedidos": ultimos_pedidos,
            "ultimas_reservas": ultimas_reservas,
            "empleados_preview": empleados_preview,
            "chart_data": chart_data,
            "hoy_label": today.strftime("%d/%m/%Y"),
            "alertas_inventario": alertas_inventario,
            "alertas_insumos": alertas_insumos,
        },
    )


@login_required(login_url='/login/')
def cancelar_reserva_cliente_view(request, pk):
    if _rol_upper(request.user) != 'CLIENTE':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        return redirect('admin_dashboard') if _rol_upper(request.user) == 'ADMINISTRADOR' else redirect('pedidos_asignados')

    if request.method != 'POST':
        return redirect('mi_perfil')

    reserva = (
        ReservaModel.objects.filter(
            pk=pk,
        ).filter(
            models.Q(user=request.user) | models.Q(email_cliente__iexact=request.user.email)
        ).first()
    )

    if not reserva:
        messages.error(request, 'Reserva no encontrada.')
        return redirect('mi_perfil')

    estado = (reserva.estado or '').upper()
    if estado in ('CANCELADA', 'CANCELADO', 'COMPLETADA', 'NO_SE_PRESENTO'):
        messages.warning(request, 'Esta reserva ya no puede cancelarse.')
        return redirect('mi_perfil')

    ReservaModel.objects.filter(pk=pk).update(estado='CANCELADA')
    messages.success(request, 'Tu reserva ha sido cancelada correctamente.')
    return redirect('mi_perfil')


@login_required(login_url='/login/')
def solicitud_turno_crear_view(request):
    if _rol_upper(request.user) != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        return redirect('admin_dashboard') if _rol_upper(request.user) == 'ADMINISTRADOR' else redirect('mi_perfil')

    if request.method == 'POST':
        form = SolicitudCambioTurnoForm(request.POST, empleado=request.user)
        if form.is_valid():
            solicitud = form.save(commit=False)
            solicitud.empleado = request.user
            solicitud.save()
            messages.success(request, 'Solicitud de cambio de turno enviada correctamente.')
            return redirect('mis_solicitudes_turno')
    else:
        form = SolicitudCambioTurnoForm(empleado=request.user)

    return render(request, 'empleado/solicitud_turno_form.html', {'form': form})


@login_required(login_url='/login/')
def mis_solicitudes_turno_view(request):
    rol = _rol_upper(request.user)
    if rol != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        if rol == 'ADMINISTRADOR':
            return redirect('admin_dashboard')
        if rol == 'CLIENTE':
            return redirect('mi_perfil')
        return redirect('login')

    solicitudes = SolicitudCambioTurnoModel.objects.filter(empleado=request.user)
    return render(request, 'empleado/mis_solicitudes_turno.html', {'solicitudes': solicitudes})


@login_required(login_url='/login/')
def mis_notificaciones_view(request):
    rol = _rol_upper(request.user)
    if rol != 'EMPLEADO':
        messages.warning(request, 'No tienes permiso para acceder a esa sección.')
        if rol == 'ADMINISTRADOR':
            return redirect('admin_dashboard')
        if rol == 'CLIENTE':
            return redirect('mi_perfil')
        return redirect('login')
    notificaciones = NotificacionModel.objects.filter(usuario=request.user)
    return render(request, 'empleado/mis_notificaciones.html', {'notificaciones': notificaciones})


@login_required(login_url='/login/')
def marcar_notificaciones_leidas_view(request):
    if request.method == 'POST':
        NotificacionModel.objects.filter(usuario=request.user, leida=False).update(leida=True)
    return redirect('mis_notificaciones')


def reservas_sse_view(request):
    if not request.user.is_authenticated or _rol_upper(request.user) != 'EMPLEADO':
        return HttpResponseForbidden()

    user_id = request.user.pk

    def event_stream():
        # Estado inicial reservas
        ultimo_reservas = {
            r['id']: r['estado']
            for r in ReservaModel.objects.values('id', 'estado')
        }
        # Estado inicial horarios del mesero
        ultimo_horarios = {
            h['id']: f"{h['hora_inicio']}|{h['hora_fin']}|{h['dia_semana']}"
            for h in HorarioModel.objects.filter(user_id=user_id)
            .values('id', 'hora_inicio', 'hora_fin', 'dia_semana')
        }

        while True:
            time.sleep(5)
            try:
                # Cambios en reservas
                actuales_r = {
                    r['id']: r['estado']
                    for r in ReservaModel.objects.values('id', 'estado')
                }
                for rid, estado in actuales_r.items():
                    anterior = ultimo_reservas.get(rid)
                    if anterior is not None and anterior != estado:
                        yield f"data: {json.dumps({'tipo': 'reserva', 'id': rid, 'estado_anterior': anterior, 'estado_nuevo': estado})}\n\n"
                    ultimo_reservas[rid] = estado
                for rid in set(actuales_r) - set(ultimo_reservas):
                    yield f"data: {json.dumps({'tipo': 'reserva', 'id': rid, 'estado_anterior': None, 'estado_nuevo': actuales_r[rid]})}\n\n"
                    ultimo_reservas[rid] = actuales_r[rid]

                # Cambios en horarios del mesero
                actuales_h = {
                    h['id']: f"{h['hora_inicio']}|{h['hora_fin']}|{h['dia_semana']}"
                    for h in HorarioModel.objects.filter(user_id=user_id)
                    .values('id', 'hora_inicio', 'hora_fin', 'dia_semana')
                }
                for hid, val in actuales_h.items():
                    anterior = ultimo_horarios.get(hid)
                    if anterior is not None and anterior != val:
                        partes = val.split('|')
                        yield f"data: {json.dumps({'tipo': 'horario', 'dia': partes[2] if len(partes) > 2 else '', 'hora_inicio': partes[0], 'hora_fin': partes[1]})}\n\n"
                    ultimo_horarios[hid] = val
                # Horarios nuevos
                for hid in set(actuales_h) - set(ultimo_horarios):
                    partes = actuales_h[hid].split('|')
                    yield f"data: {json.dumps({'tipo': 'horario_nuevo', 'dia': partes[2] if len(partes) > 2 else '', 'hora_inicio': partes[0], 'hora_fin': partes[1]})}\n\n"
                    ultimo_horarios[hid] = actuales_h[hid]
                # Horarios eliminados
                eliminados = set(ultimo_horarios) - set(actuales_h)
                for hid in eliminados:
                    partes = ultimo_horarios[hid].split('|')
                    yield f"data: {json.dumps({'tipo': 'horario_eliminado', 'dia': partes[2] if len(partes) > 2 else ''})}\n\n"
                    del ultimo_horarios[hid]

            except Exception:
                break

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
