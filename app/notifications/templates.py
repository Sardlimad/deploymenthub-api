"""Plantillas HTML de los correos. Sin E/S.

Diseño de correo: tablas, estilos en línea y fuentes del sistema (los clientes de correo ignoran <style> externos
y muchos recortan CSS moderno). Colores de la identidad de la aplicación. Todo texto variable se escapa.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

BRAND = "#1f8ea8"
BRAND_DARK = "#0d4351"
BRAND_SOFT = "#e7f4f7"
BG = "#f5f7f8"
BORDER = "#e2e8ea"
TEXT = "#1d2b30"
MUTED = "#6b7f87"
FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# (texto, fondo) de las etiquetas de estado.
TONES = {
    "neutral": ("#4a5d64", "#eaf0f2"),
    "info": ("#1f6f85", "#e1f1f6"),
    "success": ("#1d6b3b", "#dff3e7"),
    "warning": ("#8a5a00", "#fdf0d5"),
    "danger": ("#a12c2c", "#fbe3e3"),
}


@dataclass(frozen=True)
class Change:
    """Un cambio listo para mostrar: texto ya redactado, tono de su punto y comentario opcional."""

    text: str
    tone: str = "info"
    comment: str | None = None


def badge(label: str, tone: str = "neutral") -> str:
    fg, bg = TONES.get(tone, TONES["neutral"])
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;background:{bg};color:{fg};'
        f'font-size:12px;font-weight:700;letter-spacing:.2px;">{escape(label)}</span>'
    )


def button(label: str, url: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0 4px;"><tr>'
        f'<td style="border-radius:8px;background:{BRAND};">'
        f'<a href="{escape(url, quote=True)}" style="display:inline-block;padding:12px 26px;color:#ffffff;'
        f'font-family:{FONT};font-size:15px;font-weight:700;text-decoration:none;border-radius:8px;">'
        f"{escape(label)}</a></td></tr></table>"
    )


def paragraph(text: str) -> str:
    return f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:{TEXT};">{escape(text)}</p>'


def heading(text: str) -> str:
    return f'<h1 style="margin:0 0 10px;font-size:22px;line-height:1.3;color:{BRAND_DARK};">{escape(text)}</h1>'


def layout(title: str, preheader: str, content: str, footer: str) -> str:
    """Estructura común: franja de marca, tarjeta central y pie."""
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG};">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};">
<tr><td align="center" style="padding:28px 12px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="width:100%;max-width:600px;font-family:{FONT};">
    <tr><td style="padding:0 4px 14px;">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="width:34px;height:34px;border-radius:9px;background:{BRAND};color:#ffffff;text-align:center;
                   font-size:18px;font-weight:800;line-height:34px;">D</td>
        <td style="padding-left:10px;font-size:17px;font-weight:700;color:{BRAND_DARK};">DeploymentHub</td>
      </tr></table>
    </td></tr>
    <tr><td style="background:#ffffff;border:1px solid {BORDER};border-top:4px solid {BRAND};border-radius:12px;
                   padding:32px 32px 26px;">
      {content}
    </td></tr>
    <tr><td style="padding:18px 8px 0;font-size:12px;line-height:1.6;color:{MUTED};text-align:center;">
      {footer}
    </td></tr>
  </table>
</td></tr></table>
</body></html>
"""


def recovery_code_email(name: str, code: str, minutes: int) -> str:
    digits = "".join(
        f'<td style="padding:0 4px;"><div style="width:42px;height:54px;line-height:54px;text-align:center;'
        f"background:{BRAND_SOFT};border:1px solid #c4e4eb;border-radius:8px;font-size:28px;font-weight:800;"
        f'color:{BRAND_DARK};font-family:Consolas,Menlo,monospace;">{escape(ch)}</div></td>'
        for ch in code
    )
    content = (
        heading("Restablece tu contraseña")
        + paragraph(f"Hola, {name}. Usa este código para continuar con el cambio de tu contraseña:")
        + f'<table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:22px auto;">'
        f"<tr>{digits}</tr></table>"
        + f'<p style="margin:0 0 18px;text-align:center;font-size:14px;color:{MUTED};">'
        f"Vence en <strong style=\"color:{TEXT};\">{minutes} minutos</strong>.</p>"
        + f'<div style="padding:12px 14px;background:{BG};border-radius:8px;font-size:13px;line-height:1.55;'
        f'color:{MUTED};">Si no lo pediste, ignora este correo: tu contraseña no cambia. '
        "Nunca compartas este código con nadie.</div>"
    )
    footer = "Mensaje automático de DeploymentHub. Por favor, no respondas a este correo."
    return layout("Código para restablecer tu contraseña", f"Tu código es {code}. Vence en {minutes} minutos.",
                  content, footer)


def deployment_email(
    name: str,
    request_number: str,
    description: str | None,
    product: str | None,
    status_label: str,
    status_tone: str,
    changes: Sequence[Change],
    link: str | None,
    reason: str,
) -> str:
    n = len(changes)
    intro = "Hubo un cambio en esta solicitud" if n == 1 else f"Hubo {n} cambios en esta solicitud"

    rows = []
    for c in changes:
        fg, _ = TONES.get(c.tone, TONES["info"])
        comment = (
            f'<div style="margin-top:6px;padding:8px 12px;background:{BG};border-left:3px solid {BORDER};'
            f'border-radius:4px;font-size:13px;line-height:1.5;color:{MUTED};">{escape(c.comment)}</div>'
            if c.comment
            else ""
        )
        rows.append(
            f'<tr><td valign="top" style="padding:3px 12px 14px 0;"><div style="width:10px;height:10px;'
            f'margin-top:5px;border-radius:50%;background:{fg};"></div></td>'
            f'<td style="padding:0 0 14px;font-size:15px;line-height:1.5;color:{TEXT};">{escape(c.text)}{comment}</td></tr>'
        )

    detail_rows = [("Solicitud", f"<strong>{escape(request_number)}</strong>")]
    if product:
        detail_rows.append(("Producto", escape(product)))
    if description:
        detail_rows.append(("Paquete", escape(description)))
    detail_rows.append(("Estado general", badge(status_label, status_tone)))
    details = "".join(
        f'<tr><td style="padding:7px 0;width:120px;font-size:13px;color:{MUTED};">{label}</td>'
        f'<td style="padding:7px 0;font-size:14px;color:{TEXT};">{value}</td></tr>'
        for label, value in detail_rows
    )

    content = (
        heading(f"Solicitud {request_number}")
        + paragraph(f"Hola, {name}. {intro}:")
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 6px;">'
        f'{"".join(rows)}</table>'
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 0;'
        f'background:{BRAND_SOFT};border-radius:10px;"><tr><td style="padding:12px 18px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{details}</table></td></tr></table>'
        + (button("Ver la solicitud", link) if link else "")
    )
    footer = f"Recibes este aviso porque {escape(reason)}.<br>Mensaje automático de DeploymentHub."
    return layout(f"Solicitud {request_number}", f"{intro}: {request_number}", content, footer)
