"""Auth GitHub — repli PAT + flux GitHub App (HTTP et signature JWT injectés)."""
import pytest

from docagent import github_auth
from docagent.github_auth import GitHubAuthError, resolve_token


def _fake_jwt(app_id, private_key, *, now=None):
    return f"jwt-for-{app_id}"


class _FakeHttp:
    """Enregistre les appels et sert des réponses scriptées par (method, url)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, method, url, *, headers, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return self.responses[(method, url)]


# --- repli PAT ---------------------------------------------------------------
def test_pat_passthrough_no_network():
    # Aucun http/jwt requis : le PAT est renvoyé tel quel.
    assert resolve_token({"token": "ghp_direct"}, "acme/widget") == "ghp_direct"


def test_pat_alternate_keys():
    assert resolve_token({"github_token": "ghp_x"}, "acme/widget") == "ghp_x"


def test_incomplete_secret_raises():
    with pytest.raises(GitHubAuthError):
        resolve_token({}, "acme/widget")
    # app_id sans clé privée → incomplet
    with pytest.raises(GitHubAuthError):
        resolve_token({"app_id": "123"}, "acme/widget")


# --- flux GitHub App ---------------------------------------------------------
def test_app_flow_resolves_installation_then_token():
    base = "https://api.github.com"
    http = _FakeHttp({
        ("GET", f"{base}/repos/acme/widget/installation"): {"id": 987},
        ("POST", f"{base}/app/installations/987/access_tokens"): {"token": "ghs_installation"},
    })
    token = resolve_token(
        {"app_id": "42", "private_key": "PEM"}, "acme/widget",
        http=http, jwt_builder=_fake_jwt,
    )
    assert token == "ghs_installation"
    # 1) lookup installation avec le JWT en Bearer, 2) échange contre le token.
    assert http.calls[0]["method"] == "GET"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer jwt-for-42"
    assert http.calls[1]["method"] == "POST"
    assert http.calls[1]["url"].endswith("/app/installations/987/access_tokens")


def test_app_flow_uses_installation_id_from_secret():
    base = "https://api.github.com"
    http = _FakeHttp({
        ("POST", f"{base}/app/installations/555/access_tokens"): {"token": "ghs_x"},
    })
    token = resolve_token(
        {"app_id": "1", "private_key": "PEM", "installation_id": 555}, "acme/widget",
        http=http, jwt_builder=_fake_jwt,
    )
    assert token == "ghs_x"
    # Pas de lookup d'installation (fourni par le secret) : un seul appel.
    assert len(http.calls) == 1
    assert http.calls[0]["method"] == "POST"


def test_app_flow_no_installation_found():
    base = "https://api.github.com"
    http = _FakeHttp({("GET", f"{base}/repos/acme/widget/installation"): {}})
    with pytest.raises(GitHubAuthError):
        resolve_token({"app_id": "1", "private_key": "PEM"}, "acme/widget",
                      http=http, jwt_builder=_fake_jwt)


def test_app_flow_token_exchange_missing_token():
    base = "https://api.github.com"
    http = _FakeHttp({
        ("GET", f"{base}/repos/acme/widget/installation"): {"id": 1},
        ("POST", f"{base}/app/installations/1/access_tokens"): {},
    })
    with pytest.raises(GitHubAuthError):
        resolve_token({"app_id": "1", "private_key": "PEM"}, "acme/widget",
                      http=http, jwt_builder=_fake_jwt)


def test_jwt_claims_shape(monkeypatch):
    """Vérifie iss/iat/exp sans dépendre de la crypto (jwt.encode monkeypatché)."""
    captured = {}

    class _FakeJwt:
        @staticmethod
        def encode(payload, key, algorithm=None):
            captured["payload"] = payload
            captured["algorithm"] = algorithm
            captured["key"] = key
            return "signed"

    monkeypatch.setitem(__import__("sys").modules, "jwt", _FakeJwt)
    out = github_auth._build_app_jwt("APPID", "PEM", now=1_000_000)
    assert out == "signed"
    assert captured["algorithm"] == "RS256"
    assert captured["payload"]["iss"] == "APPID"
    assert captured["payload"]["iat"] == 1_000_000 - 60
    assert captured["payload"]["exp"] == 1_000_000 + github_auth._JWT_TTL_SECONDS


def test_build_app_jwt_real_rs256_roundtrip():
    """Signature RS256 réelle : génère une paire de clés, signe, puis vérifie.

    Skippé si PyJWT/cryptography ne sont pas installés (env de test minimal).
    """
    jwt = pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    token = github_auth._build_app_jwt("APP123", private_pem, now=1_000_000)
    # Décodage avec la clé publique : valide la signature RS256 (exp désactivé,
    # 'now' figé dans le passé pour un test déterministe).
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"],
                         options={"verify_exp": False})
    assert decoded["iss"] == "APP123"
    assert decoded["iat"] == 1_000_000 - 60
    assert decoded["exp"] == 1_000_000 + github_auth._JWT_TTL_SECONDS
