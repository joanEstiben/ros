import base64
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_SP_TOKEN_URL = 'https://api.sendpulse.com/oauth/access_token'
_SP_BASE = 'https://api.sendpulse.com'


def _get_token() -> str:
    resp = requests.post(
        _SP_TOKEN_URL,
        json={
            'grant_type': 'client_credentials',
            'client_id': settings.SENDPULSE_CLIENT_ID,
            'client_secret': settings.SENDPULSE_CLIENT_SECRET,
        },
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f'SendPulse auth error {resp.status_code}: {resp.text}')
    return resp.json()['access_token']


def _headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _send_email(to_email: str, to_name: str, subject: str, html: str) -> dict:
    """Envía un correo transaccional directo sin usar el sistema de campañas."""
    token = _get_token()
    
    email_data = {
        'email': {
            'html': base64.b64encode(html.encode('utf-8')).decode('ascii'),
            'subject': subject,
            'from': {
                'name': settings.SENDPULSE_FROM_NAME,
                'email': settings.SENDPULSE_FROM_EMAIL,
            },
            'to': [
                {
                    'name': to_name,
                    'email': to_email,
                }
            ],
        }
    }
    
    resp = requests.post(
        f'{_SP_BASE}/smtp/emails',
        json=email_data,
        headers=_headers(token),
        timeout=15,
    )
    
    if not resp.ok:
        raise RuntimeError(f'Error en envío directo: {resp.status_code} {resp.text}')
        
    return resp.json()


def _build_html(titulo: str, mensaje: str, color_acento: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f5f0e8">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 0">'
        '<tr><td align="center">'
        '<table width="560" cellpadding="0" cellspacing="0" '
        'style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.10)">'
        '<tr><td style="background:#1a1a1a;padding:24px 32px;text-align:center">'
        '<h1 style="margin:0;font-family:Georgia,serif;font-size:26px;color:#ffd700">&#127869;&#65039; Olla y Saz&#243;n</h1>'
        '</td></tr>'
        f'<tr><td style="background:{color_acento};height:4px"></td></tr>'
        '<tr><td style="padding:32px">'
        f'<h2 style="margin:0 0 16px;font-size:20px;color:#1a1a1a;font-family:Georgia,serif">{titulo}</h2>'
        f'<p style="margin:0;font-size:15px;color:#444;line-height:1.7">{mensaje}</p>'
        '</td></tr>'
        '<tr><td style="background:#1a1a1a;padding:16px 32px;text-align:center">'
        '<p style="margin:0;font-size:12px;color:rgba(255,255,255,.5)">'
        '&copy; Restaurante Olla y Saz&#243;n &nbsp;|&nbsp; Gracias por elegirnos</p>'
        '</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def _get_destinatario(reserva) -> tuple | None:
    if reserva.user_id:
        from users.infrastructure.models import UserModel
        try:
            user = UserModel.objects.get(pk=reserva.user_id)
            return user.email, f'{user.nombre} {user.apellido}'.strip()
        except UserModel.DoesNotExist:
            pass

    if reserva.email_cliente:
        return reserva.email_cliente, (reserva.nombre_cliente or 'Cliente')

    return None


def enviar_correo_confirmacion(reserva) -> bool:
    destinatario = _get_destinatario(reserva)
    if not destinatario:
        logger.warning('Reserva %s sin email: no se envió confirmación.', reserva.pk)
        return False

    email, nombre = destinatario
    fecha = reserva.fecha_reserva.strftime('%d/%m/%Y') if reserva.fecha_reserva else '—'
    hora = reserva.hora or '—'

    html = _build_html(
        titulo='&#10003; Reserva Confirmada',
        mensaje=(
            f'Hola <strong>{nombre}</strong>,<br><br>'
            f'Tu reserva para el <strong>{fecha}</strong> a las <strong>{hora}</strong> '
            f'ha sido confirmada.<br><br>'
            f'Código de reserva: <strong>{reserva.codigo_reserva}</strong><br><br>'
            '¡Te esperamos con mucho gusto!'
        ),
        color_acento='#28a745',
    )

    try:
        _send_email(email, nombre, '✅ Reserva confirmada — Olla y Sazón', html)
        logger.info('Confirmación enviada a %s (reserva %s).', email, reserva.pk)
        return True
    except RuntimeError as exc:
        logger.error('Error enviando confirmación reserva %s: %s', reserva.pk, exc)
        return False


def enviar_correo_rechazo(reserva) -> bool:
    destinatario = _get_destinatario(reserva)
    if not destinatario:
        logger.warning('Reserva %s sin email: no se envió rechazo.', reserva.pk)
        return False

    email, nombre = destinatario

    html = _build_html(
        titulo='&#10007; Reserva No Disponible',
        mensaje=(
            f'Hola <strong>{nombre}</strong>,<br><br>'
            'Lamentamos informarte que tu reserva no pudo ser confirmada por disponibilidad.<br><br>'
            f'Código de reserva: <strong>{reserva.codigo_reserva}</strong><br><br>'
            'Si deseas intentarlo en otra fecha u hora, no dudes en contactarnos. '
            '¡Esperamos verte pronto!'
        ),
        color_acento='#dc3545',
    )

    try:
        _send_email(email, nombre, '❌ Reserva no disponible — Olla y Sazón', html)
        logger.info('Rechazo enviado a %s (reserva %s).', email, reserva.pk)
        return True
    except RuntimeError as exc:
        logger.error('Error enviando rechazo reserva %s: %s', reserva.pk, exc)
        return False


# ── Notificaciones de PAGOS ──────────────────────────────────────────────────

def _get_email_pago(pago) -> tuple | None:
    if pago.email_cliente:
        nombre = (pago.pedido.cliente_nombre or 'Cliente') if pago.pedido_id else 'Cliente'
        return pago.email_cliente, nombre
    if pago.user_id:
        from users.infrastructure.models import UserModel
        try:
            user = UserModel.objects.get(pk=pago.user_id)
            return user.email, f'{user.nombre} {user.apellido}'.strip()
        except UserModel.DoesNotExist:
            pass
    if pago.pedido_id and pago.pedido.email_cliente:
        return pago.pedido.email_cliente, (pago.pedido.cliente_nombre or 'Cliente')
    return None


def _build_factura_html(pago) -> str:
    pedido = pago.pedido
    nombre = pedido.cliente_nombre or 'Cliente'
    detalles = pedido.detalles.select_related('producto').all()

    filas = ''.join(
        f'<tr>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #f0e6c8">{d.producto.nombre}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #f0e6c8;text-align:center">{d.cantidad}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #f0e6c8;text-align:right">${d.precio:,.0f}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #f0e6c8;text-align:right">${d.precio * d.cantidad:,.0f}</td>'
        f'</tr>'
        for d in detalles
    )

    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f5f0e8">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 0">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" '
        'style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.10)">'
        '<tr><td style="background:#1a1a1a;padding:24px 32px;text-align:center">'
        '<h1 style="margin:0;font-family:Georgia,serif;font-size:26px;color:#ffd700">&#127869;&#65039; Olla y Saz&#243;n</h1>'
        '<p style="margin:4px 0 0;font-size:12px;color:rgba(255,255,255,.5)">Factura de compra</p>'
        '</td></tr>'
        '<tr><td style="background:#28a745;height:4px"></td></tr>'
        '<tr><td style="padding:28px 32px">'
        f'<p style="margin:0 0 4px;font-size:15px;color:#333">Hola <strong>{nombre}</strong>,</p>'
        '<p style="margin:0 0 20px;font-size:15px;color:#333">Tu pago fue aprobado exitosamente. Adjuntamos tu factura correspondiente.</p>'
        f'<p style="margin:0 0 4px;font-size:12px;color:#888">Pedido <strong>#{pedido.pk}</strong> &nbsp;|&nbsp; '
        f'Método: <strong>{pago.metodo_pago}</strong></p>'
        '<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;border-collapse:collapse">'
        '<thead><tr style="background:#f5f0e8">'
        '<th style="padding:8px;text-align:left;font-size:12px">Producto</th>'
        '<th style="padding:8px;text-align:center;font-size:12px">Cant.</th>'
        '<th style="padding:8px;text-align:right;font-size:12px">Precio</th>'
        '<th style="padding:8px;text-align:right;font-size:12px">Subtotal</th>'
        '</tr></thead>'
        f'<tbody>{filas}</tbody>'
        '</table>'
        f'<p style="margin:16px 0 0;font-size:16px;font-weight:700;text-align:right;color:#1a1a1a">'
        f'Total: ${pago.monto_total:,.0f}</p>'
        '</td></tr>'
        '<tr><td style="background:#1a1a1a;padding:16px 32px;text-align:center">'
        '<p style="margin:0;font-size:12px;color:rgba(255,255,255,.5)">'
        '&copy; Restaurante Olla y Saz&#243;n &nbsp;|&nbsp; Gracias por tu compra</p>'
        '</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def enviar_correo_pago_aprobado(pago) -> bool:
    destinatario = _get_email_pago(pago)
    if not destinatario:
        logger.warning('Pago %s sin email: no se envió factura.', pago.pk)
        return False

    email, nombre = destinatario
    html = _build_factura_html(pago)

    try:
        _send_email(email, nombre, '✅ Pago aprobado - OLLA Y Sazón', html)
        logger.info('Factura enviada a %s (pago %s).', email, pago.pk)
        return True
    except RuntimeError as exc:
        logger.error('Error enviando factura pago %s: %s', pago.pk, exc)
        return False


def enviar_correo_pago_rechazado(pago) -> bool:
    destinatario = _get_email_pago(pago)
    if not destinatario:
        logger.warning('Pago %s sin email: no se envió rechazo.', pago.pk)
        return False

    email, nombre = destinatario
    motivo = pago.motivo_rechazo or 'No especificado'

    html = _build_html(
        titulo='&#10007; Pago Rechazado',
        mensaje=(
            f'Hola <strong>{nombre}</strong>,<br><br>'
            'Tu pago fue rechazado.<br><br>'
            f'<strong>Motivo:</strong><br>'
            f'<span style="color:#555">{motivo}</span><br><br>'
            'Si tienes dudas, no dudes en contactarnos. ¡Esperamos verte pronto!'
        ),
        color_acento='#dc3545',
    )

    try:
        _send_email(email, nombre, '❌ Pago rechazado - OLLA Y Sazón', html)
        logger.info('Rechazo de pago enviado a %s (pago %s).', email, pago.pk)
        return True
    except RuntimeError as exc:
        logger.error('Error enviando rechazo pago %s: %s', pago.pk, exc)
        return False