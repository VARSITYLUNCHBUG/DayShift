"""The Content-Security-Policy: on every page, with a fresh nonce, and a view's own header kept."""

from __future__ import annotations

import re

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory

from config import csp


@pytest.mark.django_db
def test_admin_pages_carry_the_policy_with_a_fresh_nonce_each() -> None:
    client = Client()
    first = client.get("/admin/login/")
    second = client.get("/admin/login/")
    policy = first["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy
    nonces = [
        re.search(r"script-src 'self' 'nonce-([^']+)'", response["Content-Security-Policy"])
        for response in (first, second)
    ]
    assert nonces[0] and nonces[1] and nonces[0].group(1) != nonces[1].group(1)


@pytest.mark.django_db
def test_the_calibration_page_marks_its_inline_code_with_the_nonce() -> None:
    staff = User.objects.create_superuser("staff", password="pw-for-tests-only")
    client = Client()
    client.force_login(staff)
    response = client.get("/admin/calibration/")
    assert response.status_code == 200
    nonce = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"])
    assert nonce
    body = response.content.decode()
    tags = re.findall(r"<(script|style)\b([^>]*)>", body)
    inline = [attrs for _tag, attrs in tags if "src=" not in attrs]
    assert inline, "the page has inline code to check"
    assert all(f'nonce="{nonce.group(1)}"' in attrs for attrs in inline)


def test_a_views_own_policy_is_kept() -> None:
    def view(request: HttpRequest) -> HttpResponse:
        response = HttpResponse("ok")
        response["Content-Security-Policy"] = "default-src 'none'"
        return response

    response = csp.csp_middleware(view)(RequestFactory().get("/"))
    assert response["Content-Security-Policy"] == "default-src 'none'"


def test_the_header_lists_each_directive_in_order() -> None:
    policy = {"default-src": ["'self'"], "script-src": ["'self'", "'nonce'"]}
    assert csp.header(policy, "abc") == "default-src 'self'; script-src 'self' 'nonce-abc'"
