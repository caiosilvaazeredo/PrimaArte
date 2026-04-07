# -*- coding: utf-8 -*-
"""
VAL'S - Shipping Service
=========================
Calculo de frete via API dos Correios (ViaCEP + calculo estimado).
"""
import os
import requests as http_requests
from dotenv import load_dotenv

load_dotenv()

# Dimensoes padrao da caixa (configuravel no admin)
DEFAULT_WEIGHT = float(os.environ.get('SHIPPING_DEFAULT_WEIGHT', '0.5'))  # kg
DEFAULT_LENGTH = float(os.environ.get('SHIPPING_DEFAULT_LENGTH', '30'))   # cm
DEFAULT_WIDTH = float(os.environ.get('SHIPPING_DEFAULT_WIDTH', '25'))     # cm
DEFAULT_HEIGHT = float(os.environ.get('SHIPPING_DEFAULT_HEIGHT', '15'))   # cm

# CEP de origem (loja)
ORIGIN_CEP = os.environ.get('SHIPPING_ORIGIN_CEP', '28900000')  # Regiao dos Lagos default


def get_address_by_cep(cep):
    """Consulta CEP via ViaCEP."""
    cep_clean = cep.replace('-', '').replace('.', '').strip()
    if len(cep_clean) != 8 or not cep_clean.isdigit():
        return None
    try:
        resp = http_requests.get(
            f'https://viacep.com.br/ws/{cep_clean}/json/',
            timeout=10
        )
        data = resp.json()
        if data.get('erro'):
            return None
        return data
    except Exception:
        return None


def calculate_shipping(cep_destino, weight=None, length=None, width=None, height=None, settings=None):
    """
    Calcula frete estimado baseado na distancia entre CEPs.
    Usa tabela simplificada por faixa de CEP (mais confiavel que APIs instáveis dos Correios).

    Retorna lista de opcoes: [{name, price, days, code}]
    """
    cep_clean = cep_destino.replace('-', '').replace('.', '').strip()
    if len(cep_clean) != 8 or not cep_clean.isdigit():
        return []

    # Usar configuracoes do admin se disponiveis
    if settings:
        w = weight or settings.get('default_weight', DEFAULT_WEIGHT)
        l = length or settings.get('default_length', DEFAULT_LENGTH)
        wd = width or settings.get('default_width', DEFAULT_WIDTH)
        h = height or settings.get('default_height', DEFAULT_HEIGHT)
        origin = settings.get('origin_cep', ORIGIN_CEP)
    else:
        w = weight or DEFAULT_WEIGHT
        l = length or DEFAULT_LENGTH
        wd = width or DEFAULT_WIDTH
        h = height or DEFAULT_HEIGHT
        origin = ORIGIN_CEP

    origin_prefix = int(origin[:3])
    dest_prefix = int(cep_clean[:3])

    # Distancia estimada por diferenca de faixas de CEP
    diff = abs(origin_prefix - dest_prefix)

    if diff <= 10:
        # Mesma regiao
        base_pac = 15.90
        base_sedex = 25.90
        days_pac = (3, 6)
        days_sedex = (1, 3)
    elif diff <= 50:
        # Regiao proxima
        base_pac = 22.90
        base_sedex = 35.90
        days_pac = (5, 8)
        days_sedex = (2, 4)
    elif diff <= 200:
        # Media distancia
        base_pac = 32.90
        base_sedex = 48.90
        days_pac = (7, 12)
        days_sedex = (3, 6)
    else:
        # Longa distancia
        base_pac = 42.90
        base_sedex = 62.90
        days_pac = (10, 15)
        days_sedex = (5, 8)

    # Ajuste por peso (acima de 0.5kg, acrescimo por kg adicional)
    weight_extra = max(0, w - 0.5) * 8.0

    # Ajuste por volume (se a caixa for grande)
    volume = (l * wd * h) / 1000.0  # em litros
    volume_extra = max(0, volume - 11.25) * 1.5  # 30x25x15 = 11.25L padrao

    pac_price = round(base_pac + weight_extra + volume_extra, 2)
    sedex_price = round(base_sedex + weight_extra + volume_extra, 2)

    options = [
        {
            'code': 'PAC',
            'name': 'PAC - Encomenda',
            'price': pac_price,
            'days_min': days_pac[0],
            'days_max': days_pac[1],
            'days_label': f'{days_pac[0]} a {days_pac[1]} dias uteis'
        },
        {
            'code': 'SEDEX',
            'name': 'SEDEX - Expresso',
            'price': sedex_price,
            'days_min': days_sedex[0],
            'days_max': days_sedex[1],
            'days_label': f'{days_sedex[0]} a {days_sedex[1]} dias uteis'
        }
    ]

    return options
