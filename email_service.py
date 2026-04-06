# -*- coding: utf-8 -*-
"""
VAL'S - Email Service
=====================
Sistema de e-mail via Gmail SMTP.
Tipos: boas-vindas, confirmacao de pedido, status de pagamento, recuperacao de senha.
"""
import smtplib
import os
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from threading import Thread

from dotenv import load_dotenv
load_dotenv()

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_NAME = os.environ.get('SMTP_FROM_NAME', "Val's - Luxury Handcrafted")

_ENABLED = bool(SMTP_USER and SMTP_PASSWORD)


def _base_html(content, preview_text=""):
    """HTML base template for all emails."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Val's</title>
<style>
  body {{ margin:0; padding:0; background:#FAF8F5; font-family:'Helvetica Neue',Arial,sans-serif; color:#2D2D2D; }}
  .wrapper {{ max-width:600px; margin:0 auto; background:#fff; }}
  .header {{ background:#1B2A4A; padding:30px 40px; text-align:center; }}
  .header h1 {{ color:#FAF8F5; font-size:28px; margin:0; letter-spacing:4px; font-weight:300; }}
  .header p {{ color:#C9A84C; font-size:10px; margin:4px 0 0; letter-spacing:3px; text-transform:uppercase; }}
  .body {{ padding:40px; }}
  .body h2 {{ color:#1B2A4A; font-size:20px; margin:0 0 20px; font-weight:400; }}
  .body p {{ font-size:14px; line-height:1.7; color:#555; margin:0 0 15px; }}
  .highlight-box {{ background:#FAF8F5; border-left:3px solid #C9A84C; padding:20px; margin:25px 0; }}
  .highlight-box p {{ margin:5px 0; font-size:14px; color:#2D2D2D; }}
  .btn {{ display:inline-block; background:#1B2A4A; color:#FAF8F5; text-decoration:none; padding:14px 35px; font-size:13px; letter-spacing:2px; text-transform:uppercase; margin:20px 0; }}
  .btn:hover {{ background:#2a3d6a; }}
  .divider {{ border:none; border-top:1px solid #E8E4DD; margin:30px 0; }}
  table.items {{ width:100%; border-collapse:collapse; margin:15px 0; }}
  table.items th {{ text-align:left; padding:10px 8px; border-bottom:2px solid #1B2A4A; font-size:12px; color:#8A8A8A; text-transform:uppercase; letter-spacing:1px; }}
  table.items td {{ padding:10px 8px; border-bottom:1px solid #E8E4DD; font-size:14px; }}
  .total-row td {{ font-weight:bold; color:#1B2A4A; font-size:16px; border-top:2px solid #1B2A4A; border-bottom:none; }}
  .footer {{ background:#1B2A4A; padding:30px 40px; text-align:center; }}
  .footer p {{ color:#8A8A8A; font-size:11px; margin:5px 0; }}
  .footer a {{ color:#C9A84C; text-decoration:none; }}
  .code-box {{ background:#1B2A4A; color:#FAF8F5; font-size:32px; letter-spacing:8px; text-align:center; padding:20px; margin:20px 0; font-weight:bold; }}
  .status-badge {{ display:inline-block; padding:6px 16px; font-size:12px; letter-spacing:1px; text-transform:uppercase; font-weight:bold; }}
  .status-paid {{ background:#d4edda; color:#155724; }}
  .status-pending {{ background:#fff3cd; color:#856404; }}
  .status-cancelled {{ background:#f8d7da; color:#721c24; }}
  .status-shipped {{ background:#cce5ff; color:#004085; }}
</style>
</head>
<body>
<span style="display:none;font-size:1px;color:#FAF8F5;max-height:0;overflow:hidden;">{preview_text}</span>
<div class="wrapper">
  <div class="header">
    <h1>VAL'S</h1>
    <p>Luxury Handcrafted</p>
  </div>
  <div class="body">
    {content}
  </div>
  <div class="footer">
    <p><a href="#">Val's - Luxury Handcrafted</a></p>
    <p>Colecao Riviera Botanica</p>
    <p style="margin-top:15px;">Este e-mail foi enviado automaticamente. Nao responda.</p>
  </div>
</div>
</body>
</html>"""


def _send_email(to_email, subject, html_content):
    """Send email via SMTP. Returns True on success."""
    if not _ENABLED:
        print(f"[Email] SMTP nao configurado. Email para {to_email} nao enviado.")
        return False

    msg = MIMEMultipart('alternative')
    msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"[Email] Enviado para {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[Email] Erro ao enviar para {to_email}: {e}")
        return False


def send_email_async(app, to_email, subject, html_content):
    """Send email in background thread (non-blocking)."""
    def _send(app_ctx):
        with app_ctx:
            _send_email(to_email, subject, html_content)
    thread = Thread(target=_send, args=(app.app_context(),))
    thread.daemon = True
    thread.start()


# ==========================================
# EMAIL TEMPLATES
# ==========================================

def send_welcome_email(app, customer_name, customer_email):
    """Send welcome email after registration."""
    content = f"""
    <h2>Bem-vinda a Val's, {customer_name}!</h2>
    <p>Estamos felizes em te-la conosco. Sua conta foi criada com sucesso.</p>
    <p>Na Val's, cada peca e feita a mao com dedicacao e carinho, inspirada na beleza da natureza e no luxo artesanal da Riviera.</p>

    <div class="highlight-box">
      <p><strong>O que voce pode fazer agora:</strong></p>
      <p>&#8226; Explorar nossa colecao exclusiva</p>
      <p>&#8226; Adicionar produtos a sua sacola</p>
      <p>&#8226; Pagar com PIX, cartao ou boleto</p>
      <p>&#8226; Acompanhar seus pedidos</p>
      <p>&#8226; Ativar autenticacao em 2 fatores para mais seguranca</p>
    </div>

    <p>Dica: Ative a verificacao em duas etapas no seu perfil para proteger sua conta.</p>
    """
    html = _base_html(content, f"Bem-vinda a Val's, {customer_name}!")
    send_email_async(app, customer_email, "Bem-vinda a Val's! ✨", html)


def send_order_confirmation_email(app, order):
    """Send order confirmation email."""
    items_html = ""
    for item in order.get('items', []):
        items_html += f"""
        <tr>
          <td>{item['name']}</td>
          <td style="text-align:center;">{item['quantity']}</td>
          <td style="text-align:right;">R$ {item['subtotal']:.2f}</td>
        </tr>"""

    payment_labels = {
        'PIX': 'PIX',
        'CREDIT_CARD': 'Cartao de Credito',
        'BOLETO': 'Boleto Bancario'
    }
    payment_label = payment_labels.get(order.get('payment_method', ''), order.get('payment_method', ''))

    content = f"""
    <h2>Pedido Confirmado!</h2>
    <p>Ola, {order.get('customer_name', '')}! Recebemos seu pedido e ele esta sendo processado.</p>

    <div class="highlight-box">
      <p><strong>Pedido:</strong> {order.get('order_number', '')}</p>
      <p><strong>Data:</strong> {datetime.now().strftime('%d/%m/%Y as %H:%M')}</p>
      <p><strong>Pagamento:</strong> {payment_label}</p>
    </div>

    <table class="items">
      <tr>
        <th>Produto</th>
        <th style="text-align:center;">Qtd</th>
        <th style="text-align:right;">Subtotal</th>
      </tr>
      {items_html}
      <tr class="total-row">
        <td colspan="2">Total</td>
        <td style="text-align:right;">R$ {order.get('total', 0):.2f}</td>
      </tr>
    </table>

    <hr class="divider">
    <p>Voce pode acompanhar o status do seu pedido na sua area de cliente.</p>
    """
    html = _base_html(content, f"Pedido {order.get('order_number', '')} confirmado!")
    send_email_async(
        app,
        order.get('customer_email', ''),
        f"Pedido {order.get('order_number', '')} - Confirmacao",
        html
    )


def send_payment_status_email(app, order):
    """Send email when payment status changes."""
    status = order.get('payment_status', '')
    order_status = order.get('status', '')

    status_configs = {
        'CONFIRMED': ('Pagamento Confirmado', 'status-paid',
                      'Seu pagamento foi confirmado com sucesso! Estamos preparando seu pedido com todo carinho.'),
        'RECEIVED': ('Pagamento Recebido', 'status-paid',
                     'Seu pagamento foi recebido! Seu pedido esta sendo preparado.'),
        'OVERDUE': ('Pagamento Vencido', 'status-cancelled',
                    'O prazo de pagamento do seu pedido expirou. Se ainda deseja receber os produtos, entre em contato conosco.'),
        'REFUNDED': ('Pagamento Estornado', 'status-cancelled',
                     'O pagamento do seu pedido foi estornado. O valor sera devolvido conforme o prazo da sua operadora.'),
    }

    if status not in status_configs:
        return

    title, badge_class, message = status_configs[status]

    content = f"""
    <h2>Atualizacao do Pedido</h2>
    <p>Ola, {order.get('customer_name', '')}!</p>

    <div class="highlight-box">
      <p><strong>Pedido:</strong> {order.get('order_number', '')}</p>
      <p><strong>Status:</strong> <span class="status-badge {badge_class}">{title}</span></p>
    </div>

    <p>{message}</p>

    <hr class="divider">
    <p>Acompanhe todos os detalhes na sua area de cliente.</p>
    """
    html = _base_html(content, f"Pedido {order.get('order_number', '')} - {title}")
    send_email_async(
        app,
        order.get('customer_email', ''),
        f"Pedido {order.get('order_number', '')} - {title}",
        html
    )


def send_order_status_email(app, order):
    """Send email when order status changes (shipped, delivered, etc)."""
    status = order.get('status', '')

    status_configs = {
        'processing': ('Em Preparacao', 'status-pending',
                       'Seu pedido esta sendo preparado com todo cuidado. Em breve ele estara a caminho!'),
        'shipped': ('Pedido Enviado', 'status-shipped',
                    'Seu pedido foi enviado! Em breve voce recebera suas pecas Val\'s.'),
        'delivered': ('Pedido Entregue', 'status-paid',
                      'Seu pedido foi entregue! Esperamos que ame suas novas pecas. Obrigada por escolher Val\'s!'),
        'cancelled': ('Pedido Cancelado', 'status-cancelled',
                      'Seu pedido foi cancelado. Se tiver duvidas, entre em contato conosco.'),
    }

    if status not in status_configs:
        return

    title, badge_class, message = status_configs[status]

    content = f"""
    <h2>Atualizacao do Pedido</h2>
    <p>Ola, {order.get('customer_name', '')}!</p>

    <div class="highlight-box">
      <p><strong>Pedido:</strong> {order.get('order_number', '')}</p>
      <p><strong>Status:</strong> <span class="status-badge {badge_class}">{title}</span></p>
    </div>

    <p>{message}</p>
    """
    html = _base_html(content, f"Pedido {order.get('order_number', '')} - {title}")
    send_email_async(
        app,
        order.get('customer_email', ''),
        f"Pedido {order.get('order_number', '')} - {title}",
        html
    )


def generate_password_reset_token():
    """Generate a secure password reset token."""
    return secrets.token_urlsafe(48)


def send_password_reset_email(app, customer_email, customer_name, reset_url):
    """Send password reset email."""
    content = f"""
    <h2>Recuperacao de Senha</h2>
    <p>Ola, {customer_name}!</p>
    <p>Recebemos uma solicitacao para redefinir a senha da sua conta Val's.</p>

    <p style="text-align:center;">
      <a href="{reset_url}" class="btn">Redefinir Minha Senha</a>
    </p>

    <p style="font-size:12px; color:#8A8A8A;">Este link expira em 1 hora. Se voce nao solicitou a redefinicao de senha, ignore este e-mail.</p>

    <hr class="divider">
    <p style="font-size:12px; color:#8A8A8A;">Se o botao nao funcionar, copie e cole este link no navegador:</p>
    <p style="font-size:11px; color:#8A8A8A; word-break:break-all;">{reset_url}</p>
    """
    html = _base_html(content, "Redefinicao de senha - Val's")
    send_email_async(app, customer_email, "Redefinicao de Senha - Val's", html)
