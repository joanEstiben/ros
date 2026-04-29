import base64
import time
import requests
from django.conf import settings

_SP_TOKEN_URL = 'https://api.sendpulse.com/oauth/access_token'
_SP_BASE = 'https://api.sendpulse.com'


def _get_token():
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


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


def _clear_list(token, book_id):
    """Elimina todos los contactos de la lista en SendPulse."""
    # Obtener todos los emails actuales en la lista
    resp = requests.get(
        f'{_SP_BASE}/addressbooks/{book_id}/emails',
        headers=_headers(token),
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f'Error obteniendo contactos: {resp.status_code} {resp.text}')
    data = resp.json()
    emails = [e['email'] for e in data] if isinstance(data, list) else []
    if not emails:
        return
    resp = requests.delete(
        f'{_SP_BASE}/addressbooks/{book_id}/emails',
        json={'emails': emails},
        headers=_headers(token),
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f'Error eliminando contactos: {resp.status_code} {resp.text}')


def _sync_clientes(token, book_id):
    """Reemplaza la lista de SendPulse con los clientes activos actuales."""
    from users.infrastructure.models import UserModel
    clientes = list(
        UserModel.objects.filter(activo=True, rol__nombre__iexact='CLIENTE')
        .values('email', 'nombre', 'apellido')
    )
    if not clientes:
        return 0

    _clear_list(token, book_id)

    emails = [
        {
            'email': c['email'],
            'variables': {'nombre': c['nombre'], 'apellido': c['apellido']},
        }
        for c in clientes
    ]
    resp = requests.post(
        f'{_SP_BASE}/addressbooks/{book_id}/emails',
        json={'emails': emails},
        headers=_headers(token),
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f'Error sincronizando contactos: {resp.status_code} {resp.text}')
    return len(emails)


def enviar_promocion_a_clientes(subject, html_body, text_body=None):
    """
    Sincroniza clientes en SendPulse y lanza una campaña de email masivo.
    """
    book_id = getattr(settings, 'SENDPULSE_LIST_ID', 633081)
    from_name = getattr(settings, 'SENDPULSE_FROM_NAME', 'Olla y Sazón')
    from_email = settings.SENDPULSE_FROM_EMAIL

    token = _get_token()

    total = _sync_clientes(token, book_id)
    if total == 0:
        return None

    campaign = {
        'sender_name': from_name,
        'sender_email': from_email,
        'subject': subject,
        'body': base64.b64encode(html_body.encode('utf-8')).decode('ascii'),
        'list_id': book_id,
    }

    # SendPulse bloquea la lista mientras copia contactos; reintentamos hasta 5 veces
    for intento in range(5):
        resp = requests.post(
            f'{_SP_BASE}/campaigns',
            json=campaign,
            headers=_headers(token),
            timeout=15,
        )
        if resp.ok:
            return resp.json()
        data = resp.json()
        if data.get('error_code') == 709:  # Book is block: copying addresses
            time.sleep(3)
            continue
        raise RuntimeError(f'Error creando campaña: {resp.status_code} {resp.text}')

    raise RuntimeError('La lista de contactos sigue bloqueada en SendPulse. Intenta de nuevo en unos segundos.')
