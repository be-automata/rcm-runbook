"""Demo chat page: serves HTML publicly, carries no secret, wires the run endpoint."""



class TestDemoPage:
    def test_served_without_key(self, client):
        # The HTML page is public; auth happens on its API calls, not the page load.
        resp = client.get("/demo")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_page_holds_no_secret(self, client):
        body = client.get("/demo").text
        assert "OSK_" not in body
        assert "sk-ant" not in body
        # It reads the key from the URL at runtime instead
        assert "URLSearchParams" in body
        assert "/agents/facilitador-rcm/runs" in body

    def test_run_endpoint_is_gated(self, client, con_llave):
        # The page's target endpoint must reject calls without the key
        resp = client.post(
            "/agents/facilitador-rcm/runs",
            data={"message": "hola", "stream": "false"},
        )
        assert resp.status_code == 401


class TestSessionContinuity:
    """El comportamiento de la continuidad de sesión se prueba ejecutando el JS
    en `test_demo_session_logic.py`. Aquí queda solo lo que ese arnés no puede
    ver: que la ruta del historial esté cerrada del lado del servidor."""

    def test_session_runs_endpoint_is_gated(self, client, con_llave):
        # La página pide el historial con la llave; sin ella no se sirve.
        assert client.get("/sessions/demo-cualquiera/runs").status_code == 401


class TestPagePolish:
    def test_favicon_is_inline(self, client):
        # Sin icono embebido el navegador pide /favicon.ico y recibe 401,
        # dejando un error rojo en la consola en cada carga.
        body = client.get("/demo").text
        assert 'rel="icon"' in body
        assert "data:image/svg+xml" in body
