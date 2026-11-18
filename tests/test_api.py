"""Flujo completo contra Postgres: sesión, catálogos, paquetes, solicitudes, destinos y permisos por rol."""
import uuid


def _id(response) -> str:
    assert response.status_code == 201, response.text
    return response.json()


def _post(client, headers, url, **json):
    return client.post(url, headers=headers, json=json)


# ------------------------------------------------------------------------------------------------ sesión

def test_health_no_pide_sesion(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_sin_token_es_401_y_con_rol_insuficiente_es_403(client, developer):
    assert client.get("/api/clients").status_code == 401
    assert client.get("/api/clients", headers={"Authorization": "Bearer basura"}).status_code == 401
    r = client.post("/api/clients", headers=developer, json={"code": "X", "name": "X"})
    assert r.status_code == 403
    assert client.get("/api/users", headers=developer).status_code == 403


def test_login_y_me(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    assert me["role"] == "ADMIN" and me["email"] == "admin@test.local"


def test_login_incorrecto_es_401_con_problem_details(client):
    r = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "mala"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Correo o contraseña incorrectos."
    assert r.headers["content-type"].startswith("application/problem+json")


def test_login_valida_los_datos(client):
    r = client.post("/api/auth/login", json={"email": "", "password": ""})
    assert r.status_code == 400
    errors = r.json()["errors"]
    assert "Email" in errors and "Password" in errors


def test_bloqueo_tras_cinco_intentos(client, admin):
    roles = client.get("/api/roles", headers=admin).json()
    role_id = next(r["id"] for r in roles if r["name"] == "DEVELOPER")
    client.post("/api/users", headers=admin, json={"name": "Lock", "email": "lock@test.local", "roleId": role_id, "password": "Clave12345"})
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "lock@test.local", "password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "lock@test.local", "password": "Clave12345"})
    assert r.status_code == 401 and "bloqueada" in r.json()["detail"]


def test_limite_de_10_intentos_por_minuto(client):
    codes = [client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_cambiar_contrasena(client, admin):
    r = client.put("/api/auth/change-password", headers=admin, json={"currentPassword": "mala", "newPassword": "Nueva12345"})
    assert r.status_code == 400 and "CurrentPassword" in r.json()["errors"]
    r = client.put("/api/auth/change-password", headers=admin, json={"currentPassword": "Admin12345", "newPassword": "corta"})
    assert r.status_code == 400 and "NewPassword" in r.json()["errors"]


def test_recuperacion_de_contrasena(client, admin):
    from app.db import new_session
    from app import repositories as repo
    from app.security import hash_password

    roles = client.get("/api/roles", headers=admin).json()
    role_id = next(r["id"] for r in roles if r["name"] == "DEVELOPER")
    client.post("/api/users", headers=admin, json={"name": "Sin clave", "email": "nuevo@test.local", "roleId": role_id})
    r = client.post("/api/auth/login", json={"email": "nuevo@test.local", "password": "Cualquiera1"})
    assert r.status_code == 401 and "no has definido" in r.json()["detail"]

    # Responde igual exista o no la cuenta.
    assert client.post("/api/auth/password-recovery", json={"email": "no-existe@test.local"}).status_code == 204
    assert client.post("/api/auth/password-recovery", json={"email": "nuevo@test.local"}).status_code == 204

    # El código real solo viaja por correo: se reemplaza por uno conocido para poder probar los pasos.
    db = new_session()
    try:
        user = repo.get_user_by_email(db, "nuevo@test.local")
        assert user.password_reset_code_hash is not None
        user.password_reset_code_hash = hash_password("123456")
        db.commit()
    finally:
        db.close()

    bad = client.post("/api/auth/password-recovery/verify", json={"email": "nuevo@test.local", "code": "000000"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/password-recovery/verify", json={"email": "nuevo@test.local", "code": "123456"})
    assert ok.status_code == 204
    reset = client.post(
        "/api/auth/password-recovery/reset", json={"email": "nuevo@test.local", "code": "123456", "password": "Definida123"}
    )
    assert reset.status_code == 204
    assert client.post("/api/auth/login", json={"email": "nuevo@test.local", "password": "Definida123"}).status_code == 200
    # El código ya no sirve.
    assert client.post("/api/auth/password-recovery/verify", json={"email": "nuevo@test.local", "code": "123456"}).status_code == 400


# ----------------------------------------------------------------------------------------------- catálogos

def test_crud_de_clientes_con_codigo_unico(client, admin):
    cid = _id(_post(client, admin, "/api/clients", code="fesc", name="FESC", isOnPremise=True))
    assert client.get(f"/api/clients/{cid}", headers=admin).json() == {
        "id": cid, "code": "FESC", "name": "FESC", "isOnPremise": True, "isActive": True,
    }
    dup = _post(client, admin, "/api/clients", code="FESC", name="Otro")
    assert dup.status_code == 409 and "FESC" in dup.json()["detail"]
    assert client.put(f"/api/clients/{cid}", headers=admin, json={"code": "FESC", "name": "FESC SA", "isOnPremise": False, "isActive": False}).status_code == 204
    got = client.get(f"/api/clients/{cid}", headers=admin).json()
    assert got["name"] == "FESC SA" and got["isActive"] is False and got["isOnPremise"] is False
    too_long = _post(client, admin, "/api/clients", code="X" * 31, name="N")
    assert too_long.status_code == 400 and "Code" in too_long.json()["errors"]
    assert client.get(f"/api/clients/{uuid.uuid4()}", headers=admin).status_code == 404
    # Las rutas no distinguen mayúsculas, como en ASP.NET.
    assert client.get("/api/Clients", headers=admin).status_code == 200
    assert client.get("/api/roles/", headers=admin).status_code == 200  # el frontend usa la barra final


def test_el_borrado_es_logico_y_libera_el_codigo(client, admin):
    cid = _id(_post(client, admin, "/api/clients", code="TEMP1", name="Temporal"))
    assert client.delete(f"/api/clients/{cid}", headers=admin).status_code == 204
    assert client.get(f"/api/clients/{cid}", headers=admin).status_code == 404
    assert all(c["id"] != cid for c in client.get("/api/clients", headers=admin).json())
    _id(_post(client, admin, "/api/clients", code="TEMP1", name="Otra vez"))


def _setup_catalog(client, admin, suffix: str):
    product = _id(_post(client, admin, "/api/products", code=f"COB{suffix}", name=f"Cobranza {suffix}"))
    env = _id(_post(client, admin, "/api/environments", code=f"PRD{suffix}", name="Producción"))
    pe = _id(_post(client, admin, "/api/productenvironments", productId=product, environmentId=env, baseUrl="https://x"))
    clients = [_id(_post(client, admin, "/api/clients", code=f"C{suffix}{i}", name=f"Cliente {suffix}{i}")) for i in range(2)]
    installations = [
        _id(_post(client, admin, "/api/installations", clientId=c, productEnvironmentId=pe, baseUrl=f"https://c{i}"))
        for i, c in enumerate(clients)
    ]
    return product, env, pe, clients, installations


def test_producto_con_ambientes_e_instalaciones(client, admin):
    product, env, pe, clients, installations = _setup_catalog(client, admin, "A")
    dto = client.get(f"/api/products/{product}", headers=admin).json()
    assert dto["environments"] == [env]
    assert dto["productEnvironments"][0]["environmentCode"] == "PRDA"
    assert _post(client, admin, "/api/productenvironments", productId=product, environmentId=env).status_code == 409
    assert client.delete(f"/api/products/{product}", headers=admin).status_code == 409
    assert client.delete(f"/api/environments/{env}", headers=admin).status_code == 409
    assert client.delete(f"/api/clients/{clients[0]}", headers=admin).status_code == 409
    assert client.delete(f"/api/productenvironments/{pe}", headers=admin).status_code == 409
    inst = client.get(f"/api/installations/{installations[0]}", headers=admin).json()
    assert inst["clientCode"] == "CA0" and inst["productCode"] == "COBA" and inst["currentPackageId"] is None
    assert [e["id"] for e in client.get(f"/api/products/{product}/environments", headers=admin).json()] == [pe]


def test_artefactos_del_catalogo(client, admin):
    product, *_ = _setup_catalog(client, admin, "B")
    aid = _id(_post(client, admin, "/api/productartifacts", productId=product, code="usp_x", name="Proc X", type="StoredProcedure", path="a/b.sql"))
    dto = client.get(f"/api/productartifacts/{aid}", headers=admin).json()
    assert dto["code"] == "USP_X" and dto["type"] == "StoredProcedure" and dto["isCustom"] is False
    assert _post(client, admin, "/api/productartifacts", productId=product, code="USP_X", name="otro", type=3).status_code == 409
    # Mismo código, otro tipo: permitido.
    _id(_post(client, admin, "/api/productartifacts", productId=product, code="usp_x", name="Tabla", type="Table"))
    listing = client.get(f"/api/products/{product}/artifacts", headers=admin).json()
    assert [a["type"] for a in listing] == ["StoredProcedure", "Table"]
    assert len(client.get(f"/api/products/{product}/artifacts?type=Table", headers=admin).json()) == 1
    assert len(client.get(f"/api/products/{product}/artifacts?search=B.SQL", headers=admin).json()) == 1
    assert client.get(f"/api/products/{product}/artifacts?type=Nada", headers=admin).status_code == 400
    bad = _post(client, admin, "/api/productartifacts", productId=product, code="Z", name="Z", type="Raro")
    assert bad.status_code == 400


# ------------------------------------------------------------------------------- paquetes y solicitudes

def test_ciclo_completo_de_una_solicitud(client, admin, developer, infra):
    product, env, pe, clients, installations = _setup_catalog(client, admin, "C")
    catalog_artifact = _id(_post(client, admin, "/api/productartifacts", productId=product, code="TBL_A", name="Tabla A", type="Table"))

    # --- Paquete: uno del catálogo y uno nuevo por tipo+código.
    r = _post(
        client, developer, "/api/deploymentpackages",
        productId=product, description="Release 1.0", branch="main", commitId="abc123",
        artifacts=[
            {"productArtifactId": catalog_artifact, "changeType": "Modified", "notes": "cambia columna"},
            {"type": "StoredProcedure", "code": "usp_nuevo", "name": "SP nuevo", "executionOrder": 5},
        ],
    )
    assert r.status_code == 201, r.text
    package = r.json()
    assert r.headers["location"] == f"/api/deploymentpackages/{package['id']}"
    assert package["newArtifactsCount"] == 1 and package["isLocked"] is False
    by_code = {a["code"]: a for a in package["artifacts"]}
    assert by_code["TBL_A"]["changeType"] == "Modified" and by_code["TBL_A"]["isNew"] is False and by_code["TBL_A"]["executionOrder"] == 1
    assert by_code["USP_NUEVO"]["changeType"] == "Added" and by_code["USP_NUEVO"]["isNew"] is True and by_code["USP_NUEVO"]["executionOrder"] == 5
    # El artefacto nuevo entró al catálogo.
    assert {a["code"] for a in client.get(f"/api/products/{product}/artifacts", headers=admin).json()} == {"TBL_A", "USP_NUEVO"}

    # Un artefacto existente no puede marcarse como nuevo.
    dup = _post(client, developer, f"/api/deploymentpackages/{package['id']}/artifacts", productArtifactId=catalog_artifact, changeType="Added")
    assert dup.status_code == 409

    # --- Solicitud en borrador.
    r = _post(client, developer, "/api/deploymentrequests", packageId=package["id"], comment="Urgente", tickets=["TK-1", "tk-1", "TK-2"])
    assert r.status_code == 201, r.text
    req = r.json()
    rid = req["id"]
    assert req["status"] == "Draft" and req["displayNumber"].startswith("DR-") and req["tickets"] == ["TK-1", "TK-2"]
    assert req["createdByName"] == "Developer"

    # No se puede enviar sin destinos.
    assert client.post(f"/api/deploymentrequests/{rid}/submit", headers=developer).status_code == 409

    r = _post(client, developer, f"/api/deploymentrequests/{rid}/targets", installationIds=installations)
    assert r.status_code == 200 and len(r.json()) == 2
    assert _post(client, developer, f"/api/deploymentrequests/{rid}/targets", installationIds=installations[:1]).status_code == 409

    # Infraestructura no puede armar ni enviar; el desarrollador no puede aprobar.
    assert client.post(f"/api/deploymentrequests/{rid}/submit", headers=infra).status_code == 403
    assert client.post(f"/api/deploymentrequests/{rid}/submit", headers=developer).status_code == 204
    assert client.post(f"/api/deploymentrequests/{rid}/approve", headers=developer).status_code == 403

    # El paquete queda bloqueado.
    assert client.get(f"/api/deploymentpackages/{package['id']}", headers=developer).json()["isLocked"] is True
    assert client.delete(f"/api/deploymentpackages/{package['id']}", headers=developer).status_code == 409
    assert client.put(f"/api/deploymentpackages/{package['id']}", headers=developer, json={"description": "otro"}).status_code == 409

    detail = client.get(f"/api/deploymentrequests/{rid}", headers=developer).json()
    assert detail["status"] == "Pending" and detail["submittedByName"] == "Developer"
    assert detail["targetsTotal"] == 2 and detail["targetsPending"] == 2
    assert client.post(f"/api/deploymentrequests/{rid}/approve", headers=infra).status_code == 204
    assert client.get(f"/api/deploymentrequests/{rid}", headers=infra).json()["status"] == "Approved"

    # Instalaciones con solicitud pendiente.
    statuses = client.get(f"/api/installations?productId={product}", headers=infra).json()
    assert all(s["pendingRequestId"] == rid for s in statuses)

    # --- Reporte por cliente.
    t1, t2 = (t["id"] for t in detail["targets"])
    first_pa = package["artifacts"][0]["id"]
    # Fallar exige motivo.
    assert client.put(f"/api/deploymentrequests/{rid}/targets/{t1}/status", headers=infra, json={"status": "Failed"}).status_code == 400
    # Applied con un artefacto fallido: no permitido.
    r = client.put(
        f"/api/deploymentrequests/{rid}/targets/{t1}/status", headers=infra,
        json={"status": "Applied", "artifactResults": [{"packageArtifactId": first_pa, "status": "Failed"}]},
    )
    assert r.status_code == 409

    r = client.put(f"/api/deploymentrequests/{rid}/targets/{t1}/status", headers=infra, json={"status": "InProgress"})
    assert r.status_code == 200 and r.json()["status"] == "InProgress"
    r = client.put(f"/api/deploymentrequests/{rid}/targets/{t1}/status", headers=infra, json={"status": "Applied", "comment": "ok"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "InProgress"  # el otro cliente sigue pendiente
    target1 = next(t for t in body["targets"] if t["id"] == t1)
    assert target1["status"] == "Applied" and target1["attempts"] == 1
    assert len(target1["artifactResults"]) == 2 and all(a["status"] == "Applied" for a in target1["artifactResults"])
    assert [h["toStatus"] for h in target1["history"]] == ["Applied", "InProgress"]
    assert target1["history"][0]["changedByName"] == "Infra"
    assert target1["nextStatuses"] == ["RolledBack"]

    # La instalación recuerda el paquete aplicado.
    inst = client.get(f"/api/installations/{installations[0]}", headers=infra).json()
    assert inst["currentPackageId"] == package["id"] and inst["currentPackageDescription"] == "Release 1.0"

    # Estado de versión: el segundo cliente está desactualizado.
    outdated = client.get(f"/api/installations?productId={product}&onlyOutdated=true", headers=infra).json()
    assert [o["id"] for o in outdated] == [installations[1]]
    assert outdated[0]["latestPackageId"] == package["id"] and outdated[0]["isOutdated"] is True

    # Falla el segundo y se reintenta.
    r = client.put(f"/api/deploymentrequests/{rid}/targets/{t2}/status", headers=infra, json={"status": "Failed", "comment": "timeout"})
    assert r.json()["status"] == "PartiallyCompleted"
    r = client.put(f"/api/deploymentrequests/{rid}/targets/{t2}/status", headers=infra, json={"status": "Applied"})
    assert r.json()["status"] == "Completed" and r.json()["completedAt"] is not None
    t2dto = next(t for t in r.json()["targets"] if t["id"] == t2)
    assert t2dto["attempts"] == 2 and t2dto["errorComment"] is None

    # Una transición no permitida.
    assert client.put(f"/api/deploymentrequests/{rid}/targets/{t2}/status", headers=infra, json={"status": "Failed", "comment": "x"}).status_code == 409
    # Ya terminó: no se cancela.
    assert client.post(f"/api/deploymentrequests/{rid}/cancel", headers=developer).status_code == 409

    # Revertir el primero devuelve la instalación a como estaba.
    r = client.put(f"/api/deploymentrequests/{rid}/targets/{t1}/status", headers=infra, json={"status": "RolledBack", "comment": "mal"})
    assert r.status_code == 200 and r.json()["status"] == "PartiallyCompleted"
    inst = client.get(f"/api/installations/{installations[0]}", headers=infra).json()
    assert inst["currentPackageId"] is None

    # --- Búsqueda.
    number = detail["requestNumber"]
    page = client.get(f"/api/deploymentrequests?search={detail['displayNumber']}&pageSize=5", headers=developer).json()
    assert page["totalCount"] == 1 and page["items"][0]["id"] == rid and page["page"] == 1 and page["pageSize"] == 5
    assert page["items"][0]["createdByName"] == "Developer"
    assert client.get(f"/api/deploymentrequests?search={number}", headers=developer).json()["totalCount"] == 1
    assert client.get("/api/deploymentrequests?search=tk-2", headers=developer).json()["totalCount"] >= 1
    assert client.get(f"/api/deploymentrequests?status=PartiallyCompleted&status=Failed&productId={product}", headers=developer).json()["totalCount"] == 1
    assert client.get(f"/api/deploymentrequests?status=Draft&productId={product}", headers=developer).json()["totalCount"] == 0
    assert client.get(f"/api/deploymentrequests?clientId={clients[0]}", headers=developer).json()["totalCount"] == 1
    assert client.get(f"/api/deploymentrequests?mine=true&productId={product}", headers=developer).json()["totalCount"] == 1
    assert client.get(f"/api/deploymentrequests?mine=true&productId={product}", headers=infra).json()["totalCount"] == 0
    assert client.get("/api/deploymentrequests?pageSize=500", headers=developer).status_code == 400
    assert client.get("/api/deploymentrequests?status=Nada", headers=developer).status_code == 400


def test_cancelar_borrador_y_solicitud_enviada(client, admin, developer, infra):
    product, env, pe, clients, installations = _setup_catalog(client, admin, "D")
    package = _post(client, developer, "/api/deploymentpackages", productId=product, description="P", artifacts=[{"type": "Table", "code": "t1"}]).json()

    # Borrador: se descarta sin más.
    draft = client.post("/api/deploymentrequests", headers=developer).json()
    assert draft["status"] == "Draft"
    assert client.post(f"/api/deploymentrequests/{draft['id']}/cancel", headers=developer, json={"reason": "no va"}).status_code == 204
    assert client.get(f"/api/deploymentrequests/{draft['id']}", headers=developer).json()["status"] == "Cancelled"

    # Enviada: los pendientes se cancelan.
    rid = _post(client, developer, "/api/deploymentrequests", packageId=package["id"]).json()["id"]
    _post(client, developer, f"/api/deploymentrequests/{rid}/targets", installationIds=installations)
    client.post(f"/api/deploymentrequests/{rid}/submit", headers=developer)
    assert client.post(f"/api/deploymentrequests/{rid}/cancel", headers=developer, json={"reason": "cambio de plan"}).status_code == 204
    detail = client.get(f"/api/deploymentrequests/{rid}", headers=developer).json()
    assert detail["status"] == "Cancelled" and detail["cancellationReason"] == "cambio de plan"
    assert all(t["status"] == "Cancelled" for t in detail["targets"])
    assert all(t["nextStatuses"] == [] for t in detail["targets"])


def test_actualizacion_personalizada_para_un_cliente(client, admin, developer, infra):
    product, env, pe, clients, installations = _setup_catalog(client, admin, "E")
    general = _id(_post(client, admin, "/api/productartifacts", productId=product, code="RPT_PAGARE", name="Pagaré", type="Report"))

    # Paquete personalizado para el cliente 0: el artefacto por código entra como versión del cliente.
    custom = _post(
        client, developer, "/api/deploymentpackages",
        productId=product, description="Custom C0", customClientId=clients[0],
        artifacts=[{"type": "Report", "code": "rpt_pagare"}],
    ).json()
    assert custom["isCustom"] is True and custom["customClientId"] == clients[0]
    art = custom["artifacts"][0]
    assert art["isNew"] is True and art["ownerClientId"] == clients[0] and art["productArtifactId"] != general
    assert len(client.get(f"/api/products/{product}/artifacts", headers=admin).json()) == 2

    # Elegir la versión general en el paquete del cliente: se usa la versión del cliente (ya existe).
    again = client.post(f"/api/deploymentpackages/{custom['id']}/artifacts", headers=developer, json={"productArtifactId": general})
    assert again.status_code == 409  # ya está en el paquete

    rid = _post(client, developer, "/api/deploymentrequests", packageId=custom["id"]).json()["id"]
    # Solo puede ir a su cliente.
    assert _post(client, developer, f"/api/deploymentrequests/{rid}/targets", installationIds=[installations[1]]).status_code == 409
    assert _post(client, developer, f"/api/deploymentrequests/{rid}/targets", installationIds=[installations[0]]).status_code == 200
    client.post(f"/api/deploymentrequests/{rid}/submit", headers=developer)
    tid = client.get(f"/api/deploymentrequests/{rid}", headers=infra).json()["targets"][0]["id"]
    assert client.put(f"/api/deploymentrequests/{rid}/targets/{tid}/status", headers=infra, json={"status": "Applied"}).json()["status"] == "Completed"
    # Un paquete personalizado no cambia la versión vigente de nadie.
    assert client.get(f"/api/installations/{installations[0]}", headers=infra).json()["currentPackageId"] is None
    statuses = client.get(f"/api/installations?productId={product}", headers=infra).json()
    assert all(not s["isOutdated"] and s["latestPackageId"] is None for s in statuses)


def test_quitar_un_artefacto_nuevo_lo_retira_del_catalogo(client, admin, developer):
    product, *_ = _setup_catalog(client, admin, "F")
    package = _post(client, developer, "/api/deploymentpackages", productId=product, description="P", artifacts=[{"type": "View", "code": "v1"}]).json()
    pa = package["artifacts"][0]["id"]
    assert len(client.get(f"/api/products/{product}/artifacts", headers=admin).json()) == 1
    assert client.put(f"/api/deploymentpackages/{package['id']}/artifacts/{pa}", headers=developer, json={"executionOrder": 0}).status_code == 400
    assert client.put(f"/api/deploymentpackages/{package['id']}/artifacts/{pa}", headers=developer, json={"executionOrder": 3, "notes": "n"}).status_code == 204
    got = client.get(f"/api/deploymentpackages/{package['id']}/artifacts/{pa}", headers=developer).json()
    assert got["executionOrder"] == 3 and got["notes"] == "n"
    assert client.delete(f"/api/deploymentpackages/{package['id']}/artifacts/{pa}", headers=developer).status_code == 204
    assert client.get(f"/api/products/{product}/artifacts", headers=admin).json() == []

    # Borrar un paquete sin usar también retira lo que introdujo.
    package2 = _post(client, developer, "/api/deploymentpackages", productId=product, description="P2", artifacts=[{"type": "View", "code": "v2"}]).json()
    assert client.delete(f"/api/deploymentpackages/{package2['id']}", headers=developer).status_code == 204
    assert client.get(f"/api/deploymentpackages/{package2['id']}", headers=developer).status_code == 404
    assert client.get(f"/api/products/{product}/artifacts", headers=admin).json() == []


def test_usuarios_y_roles(client, admin):
    roles = client.get("/api/roles", headers=admin).json()
    assert {r["name"] for r in roles} >= {"ADMIN", "INFRA", "DEVELOPER"}
    dev_role = next(r["id"] for r in roles if r["name"] == "DEVELOPER")
    assert _post(client, admin, "/api/roles", name="developer").status_code == 409
    uid = _id(_post(client, admin, "/api/users", name="Ana", email="  ANA@Test.Local ", roleId=dev_role))
    user = client.get(f"/api/users/{uid}", headers=admin).json()
    assert user["email"] == "ana@test.local" and user["hasPassword"] is False and user["roleCode"] == "DEVELOPER"
    assert _post(client, admin, "/api/users", name="Otra", email="ana@test.local", roleId=dev_role).status_code == 409
    assert _post(client, admin, "/api/users", name="X", email="x@test.local", roleId=dev_role, password="123").status_code == 400
    assert client.delete(f"/api/roles/{dev_role}", headers=admin).status_code == 409
    me = client.get("/api/auth/me", headers=admin).json()
    own = client.get(f"/api/users/{me['id']}", headers=admin).json()
    r = client.put(f"/api/users/{me['id']}", headers=admin, json={"name": own["name"], "email": own["email"], "roleId": own["roleId"], "isActive": False})
    assert r.status_code == 409 and "propio usuario" in r.json()["detail"]
    assert client.delete(f"/api/users/{uid}", headers=admin).status_code == 204
    assert client.get(f"/api/users/{uid}", headers=admin).status_code == 404


def test_json_invalido_es_400(client, admin):
    r = client.post("/api/clients", headers={**admin, "Content-Type": "application/json"}, content="{no es json")
    assert r.status_code == 400
    r = client.get("/api/clients/no-es-guid", headers=admin)
    assert r.status_code == 400
