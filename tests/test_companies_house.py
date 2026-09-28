import base64
import json

import httpx
import pytest

from deallens.companies_house import CompaniesHouse, CompaniesHouseError

PROFILE = {"company_name": "TEST PLC", "company_number": "00000001", "company_status": "active"}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "mock-api-key")
    return {"cache_dir": tmp_path, "sleep": lambda delay: None}


def test_environment_key_required(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    with pytest.raises(CompaniesHouseError, match="environment"):
        CompaniesHouse()


def test_profile_auth_and_cache(setup):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"mock-api-key:").decode()
        assert request.url.path == "/company/00000001"
        assert request.extensions["timeout"]["read"] == 15
        return httpx.Response(200, json=PROFILE)
    with CompaniesHouse(**setup, transport=httpx.MockTransport(handler)) as client:
        assert client.profile("00000001").company_name == "TEST PLC"
        client.profile("00000001")
    assert len(seen) == 1
    assert "mock-api-key" not in next(setup["cache_dir"].glob("*.json")).read_text()


@pytest.mark.parametrize("method,payload,path", [
    ("search", {"items": [{"title": "TEST PLC", "company_number": "00000001"}], "total_results": 1, "start_index": 0, "items_per_page": 10}, "/search/companies"),
    ("filings", {"items": [{"transaction_id": "f1", "date": "2024-01-01", "type": "AA", "description": "accounts-with-accounts-type-full"}], "total_count": 1, "start_index": 0, "items_per_page": 10}, "/company/00000001/filing-history")])
def test_typed_paginated_reads(setup, method, payload, path):
    def handler(request):
        assert request.url.path == path
        assert request.url.params["items_per_page"] == "10"
        return httpx.Response(200, json=payload)
    with CompaniesHouse(**setup, transport=httpx.MockTransport(handler)) as client:
        result = getattr(client, method)("Test plc" if method == "search" else "00000001", items_per_page=10)
        assert len(result.items) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 301])
def test_nonretryable_status(setup, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status)
    with CompaniesHouse(**setup, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CompaniesHouseError, match=str(status)):
            client.profile("00000001")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_bounded_retry_then_success(setup, status):
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "2"}) if len(calls) == 1 else httpx.Response(200, json=PROFILE)
    with CompaniesHouse(**(setup | {"sleep": waits.append}), transport=httpx.MockTransport(handler)) as client:
        assert client.profile("00000001").company_number == "00000001"
    assert len(calls) == 2 and waits == [2]


def test_rate_limit_without_retry_after_stops_without_early_retry(setup):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429)
    with CompaniesHouse(**setup, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CompaniesHouseError, match="300 seconds"):
            client.profile("00000001")
    assert len(calls) == 1


def test_transport_timeout_retries_bounded(setup):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("mock timeout")
    with CompaniesHouse(**setup, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CompaniesHouseError, match="bounded retries"):
            client.profile("00000001")
    assert len(calls) == 3


@pytest.mark.parametrize("payload", [{}, [], {"company_name": "TEST"}])
def test_invalid_payload_not_cached(setup, payload):
    with CompaniesHouse(**setup, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        with pytest.raises(CompaniesHouseError, match="invalid JSON"):
            client.profile("00000001")
    assert list(setup["cache_dir"].glob("*.json")) == []


def test_expired_and_corrupt_cache_refetched(setup):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=PROFILE)
    with CompaniesHouse(**setup, transport=httpx.MockTransport(handler), clock=lambda: 100) as client:
        client.profile("00000001")
        path = next(setup["cache_dir"].glob("*.json"))
        path.write_text("bad json")
        client.profile("00000001")
        cached = json.loads(path.read_text())
        cached["fetched_at"] = -10000
        path.write_text(json.dumps(cached))
        client.profile("00000001")
    assert len(seen) == 3


@pytest.mark.parametrize("number", ["1", "../../xx", "12345678?key=", "0000000/"])
def test_bad_company_numbers(setup, number):
    with CompaniesHouse(**setup, transport=httpx.MockTransport(lambda request: pytest.fail("network called"))) as client:
        with pytest.raises(ValueError):
            client.profile(number)


def test_http_date_retry_after(setup):
    seen, waits = [], []
    def handler(request):
        seen.append(request)
        return httpx.Response(429, headers={"Retry-After": "Thu, 01 Jan 1970 00:00:05 GMT"}) if len(seen) == 1 else httpx.Response(200, json=PROFILE)
    with CompaniesHouse(**(setup | {"sleep": waits.append}), clock=lambda: 0, transport=httpx.MockTransport(handler)) as client:
        client.profile("00000001")
    assert waits == [5]


@pytest.mark.parametrize('header', ['-1', '-inf', 'nan', 'inf', '1.5', 'not-a-date', '+2', '9' * 1000])
def test_invalid_retry_after_never_causes_early_rate_limit_retry(setup, header):
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': header})
    with CompaniesHouse(**(setup | {'sleep': waits.append}), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CompaniesHouseError, match='300 seconds'):
            client.profile('00000001')
    assert len(calls) == 1
    assert waits == []


@pytest.mark.parametrize('setting', ['timeout', 'max_retry_wait', 'cache_ttl'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), True, '15'])
def test_invalid_numeric_configuration_fails_before_request(setup, setting, value):
    with pytest.raises(ValueError, match='configuration'):
        CompaniesHouse(**(setup | {setting: value}),
                       transport=httpx.MockTransport(lambda request: pytest.fail('network called')))


@pytest.mark.parametrize('value', [True, 1.5, float('nan'), '3', 0, 6])
def test_attempt_count_is_bounded_integer(setup, value):
    with pytest.raises(ValueError, match='configuration'):
        CompaniesHouse(**setup, max_attempts=value)


def test_cache_write_and_cleanup_failures_preserve_valid_response(setup, monkeypatch):
    from pathlib import Path
    def denied(*args, **kwargs):
        raise PermissionError('cache is not writable')
    monkeypatch.setattr(Path, 'replace', denied)
    monkeypatch.setattr(Path, 'unlink', denied)
    with CompaniesHouse(**setup, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=PROFILE))) as client:
        assert client.profile('00000001').company_number == '00000001'


@pytest.mark.parametrize('command,argument,payload', [
    ('profile', '00000001', PROFILE),
    ('search', 'Test', {'items': [], 'total_results': 0, 'start_index': 0, 'items_per_page': 100}),
    ('filings', '00000001', {'items': [], 'total_count': 0, 'start_index': 0, 'items_per_page': 100}),
])
def test_cli_metadata_commands_never_open_transaction_store(setup, monkeypatch, capsys, command, argument, payload):
    import deallens.cli as cli
    import deallens.companies_house as module
    real_client = CompaniesHouse
    monkeypatch.setattr(module, 'CompaniesHouse', lambda: real_client(
        **setup, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))))
    monkeypatch.setattr(cli, 'Store', lambda *args: pytest.fail('Metadata lookup opened transaction database'))
    assert cli.main(['companies-house', command, argument]) == 0
    expected = payload | ({'type': None, 'date_of_creation': None, 'registered_office_address': {}}
                          if command == 'profile' else {})
    assert json.loads(capsys.readouterr().out) == expected
