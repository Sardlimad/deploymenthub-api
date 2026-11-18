"""Tiempo real (protocolo de SignalR), firmador de KRUD y avisos por correo."""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

RS = "\x1e"


def _frames(text: str) -> list[dict]:
    return [json.loads(p) for p in text.split(RS) if p]


def test_negociar_exige_sesion_y_ofrece_solo_websockets(client, admin):
    assert client.post("/hubs/deployments/negotiate?negotiateVersion=1").status_code == 401
    r = client.post("/hubs/deployments/negotiate?negotiateVersion=1", headers=admin)
    body = r.json()
    assert r.status_code == 200 and body["negotiateVersion"] == 1
    assert [t["transport"] for t in body["availableTransports"]] == ["WebSockets"]
    assert body["connectionToken"] and body["connectionId"]


def test_el_websocket_sin_token_se_rechaza(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/hubs/deployments?id=x"):
            pass


def test_los_eventos_llegan_al_cliente_con_el_formato_de_signalr(client, admin, developer):
    token = admin["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/hubs/deployments?id=abc&access_token={token}") as ws:
        ws.send_text(json.dumps({"protocol": "json", "version": 1}) + RS)
        assert _frames(ws.receive_text()) == [{}]

        r = client.post("/api/deploymentrequests", headers=developer, json={"comment": "en vivo"})
        assert r.status_code == 201
        request_id = r.json()["id"]

        message = _frames(ws.receive_text())[0]
        assert message["type"] == 1 and message["target"] == "deploymentEvent"
        event = message["arguments"][0]
        assert event["type"] == "deployment.created"
        assert event["requestId"] == request_id
        assert event["occurredAt"]
        assert event["payload"]["status"] == "Draft"
        assert event["payload"]["displayNumber"].startswith("DR-")

        # Un ping del cliente no rompe nada.
        ws.send_text(json.dumps({"type": 6}) + RS)
        client.put(f"/api/deploymentrequests/{request_id}", headers=developer, json={"comment": "editada"})
        assert _frames(ws.receive_text())[0]["arguments"][0]["type"] == "deployment.updated"


def test_aserciones_de_krud(client, admin, monkeypatch):
    # Sin clave configurada responde 404.
    assert client.get("/api/krud/asercion", headers=admin).status_code == 404
    assert client.get("/api/krud/asercion").status_code == 401

    from app import state
    from app.config import get_settings
    from app.security import KrudAssertionSigner
    from jwt.algorithms import ECAlgorithm

    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(private_key))
    jwk["kid"] = "k1"
    settings = get_settings().model_copy(update={"krud_issuer": "velo-deploymenthub-dev", "krud_private_jwk": json.dumps(jwk)})
    monkeypatch.setattr(state, "get_krud_signer", lambda: KrudAssertionSigner(settings))
    from app.routers import krud

    monkeypatch.setattr(krud, "get_krud_signer", lambda: KrudAssertionSigner(settings))

    r = client.get("/api/krud/asercion", headers=admin)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("text/plain")
    header = jwt.get_unverified_header(r.text)
    assert header["alg"] == "ES256" and header["kid"] == "k1"
    claims = jwt.decode(
        r.text, private_key.public_key(), algorithms=["ES256"], audience="velo-krud", issuer="velo-deploymenthub-dev"
    )
    me = client.get("/api/auth/me", headers=admin).json()
    assert claims["sub"] == me["id"] == claims["userId"]
    assert claims["permissions"] == ["role:ADMIN", "deployhub.deploy", "deployhub.operate", "deployhub.admin"]
    assert 0 < claims["exp"] - claims["iat"] <= 120 and len(claims["jti"]) == 32


def test_la_clave_de_krud_debe_ser_ec_p256_privada():
    from app.config import get_settings
    from app.security import KrudAssertionSigner

    base = get_settings()
    bad = base.model_copy(update={"krud_issuer": "x", "krud_private_jwk": json.dumps({"kty": "RSA"})})
    with pytest.raises(RuntimeError, match="EC P-256"):
        KrudAssertionSigner(bad)


def test_los_cambios_de_una_solicitud_enviada_avisan_por_correo(client, admin, developer, infra, monkeypatch):
    from app.notifications.email import EmailSender
    from tests.test_api import _id, _post, _setup_catalog

    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(EmailSender, "send", lambda self, to, subject, body: sent.append((to, subject, body)))

    product, env, pe, clients, installations = _setup_catalog(client, admin, "N")
    package = _post(client, developer, "/api/deploymentpackages", productId=product, description="Paquete N", artifacts=[{"type": "Table", "code": "t"}]).json()
    rid = _post(client, developer, "/api/deploymentrequests", packageId=package["id"]).json()["id"]
    _post(client, developer, f"/api/deploymentrequests/{rid}/targets", installationIds=installations[:1])
    assert client.post(f"/api/deploymentrequests/{rid}/submit", headers=developer).status_code == 204

    deadline = time.time() + 10
    while not sent and time.time() < deadline:
        time.sleep(0.1)

    recipients = {to for to, _, _ in sent}
    # Admin e Infra reciben el aviso; el desarrollador que hizo el cambio no.
    assert "admin@test.local" in recipients and "infra@test.local" in recipients and "dev@test.local" not in recipients
    subject = sent[0][1]
    assert subject.endswith("enviada, pendiente de aplicar") and subject.startswith("[DeploymentHub] DR-")
    assert "Paquete N" in sent[0][2] and "Developer la envió a 1 cliente." in sent[0][2]
