# Correo gratis con Google Apps Script

Render (plan gratuito) bloquea SMTP, y los proveedores de correo piden dominio propio. Este método usa tu cuenta de
Gmail desde un script gratuito de Google; el backend le hace un POST HTTPS.

## 1. Crear el script

1. Entra a <https://script.google.com> → **Nuevo proyecto**.
2. Borra el contenido y pega el código de abajo. Cambia `SECRETO` por una clave larga y aleatoria
   (por ejemplo la salida de `python -c "import secrets; print(secrets.token_urlsafe(32))"`).

```javascript
const SECRETO = "CAMBIA_ESTA_CLAVE";

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== SECRETO) return salida({ ok: false, error: "unauthorized" });
    if (!data.to || !data.subject) return salida({ ok: false, error: "bad request" });
    MailApp.sendEmail({ to: data.to, subject: data.subject, body: data.body || "", name: "DeploymentHub" });
    return salida({ ok: true });
  } catch (err) {
    return salida({ ok: false, error: String(err) });
  }
}

function salida(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
```

## 2. Publicarlo

1. **Implementar → Nueva implementación → Tipo: Aplicación web**.
2. *Ejecutar como*: **Yo**. *Quién tiene acceso*: **Cualquier persona**
   (la clave `SECRETO` es lo que protege el envío).
3. **Implementar** y autoriza los permisos de Gmail (aviso «app no verificada» → Avanzado → Continuar).
4. Copia la **URL de la aplicación web** (termina en `/exec`).

Si cambias el código más tarde, crea una **nueva versión** de la implementación (la URL se mantiene).

## 3. Configurar el backend (Render → Environment)

| Variable | Valor |
|---|---|
| `EMAIL_WEBHOOK_URL` | la URL `/exec` |
| `EMAIL_WEBHOOK_SECRET` | el mismo valor que `SECRETO` |

Guarda; Render reinicia el servicio. Prueba con «Olvidé mi contraseña».

## Notas

- Los correos salen desde tu Gmail. Google limita los destinatarios por día (unos 100 en Gmail gratuito:
  consulta [las cuotas](https://developers.google.com/apps-script/guides/services/quotas)).
- Cualquiera con la URL y la clave podría enviar correos desde tu cuenta: no las publiques.
