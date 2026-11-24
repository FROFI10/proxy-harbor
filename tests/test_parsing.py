import time
from dataclasses import FrozenInstanceError

import pytest


def test_public_text_candidates_have_stable_immutable_identity():
    from proxyharbor.parsing import parse_candidates

    candidates = parse_candidates("8.8.8.8:8080\n1.1.1.1:3128\n8.8.8.8:8080")
    assert [(p.host, p.port, p.protocol) for p in candidates] == [
        ("8.8.8.8", 8080, "http"),
        ("1.1.1.1", 3128, "http"),
    ]
    assert candidates[0].key == "http://8.8.8.8:8080"
    assert candidates[0].url == candidates[0].key
    assert candidates[0].address == "8.8.8.8:8080"
    with pytest.raises(FrozenInstanceError):
        candidates[0].port = 80


def test_parser_rejects_non_public_non_literal_credentials_and_invalid_ports():
    from proxyharbor.parsing import parse_candidates

    invalid = [
        "127.0.0.1:80",
        "10.0.0.1:80",
        "192.168.1.1:80",
        "172.16.0.1:80",
        "169.254.1.1:80",
        "100.64.0.1:80",
        "0.0.0.0:80",
        "255.255.255.255:80",
        "224.0.0.1:80",
        "192.0.2.1:80",
        "[::1]:80",
        "[fe80::1]:80",
        "[fc00::1]:80",
        "localhost:80",
        "example.com:80",
        "8.8.8.8:0",
        "8.8.8.8:65536",
        "8.8.8.8:-1",
        "8.8.8.8:12.5",
        "http://user:password@8.8.8.8:80",
        "ftp://8.8.8.8:80",
        "008.008.008.008:80",
        "junk",
        "",
        "1.2.3.999:80",
    ]
    assert parse_candidates("\n".join(invalid)) == []
    assert parse_candidates("\n".join(invalid + ["8.8.8.8:65535"]))[0].port == 65535


def test_mixed_urls_normalize_https_ipv6_and_protocol_scoped_deduplication():
    from proxyharbor.parsing import parse_candidates

    candidates = parse_candidates(
        "https://1.1.1.1:443\nhttp://1.1.1.1:443\n"
        "socks4://8.8.8.8:1080\nsocks5://8.8.8.8:1080\n"
        "socks5://[2606:4700:4700:0:0:0:0:1111]:1080\n"
        "socks5://[2606:4700:4700::1111]:1080\n"
        "[2001:4860:4860::8888]:3128\n2001:4860:4860::8888:3128"
    )
    assert [p.url for p in candidates] == [
        "http://1.1.1.1:443",
        "socks4://8.8.8.8:1080",
        "socks5://8.8.8.8:1080",
        "socks5://[2606:4700:4700::1111]:1080",
        "http://[2001:4860:4860::8888]:3128",
    ]
    assert candidates[-1].address == "[2001:4860:4860::8888]:3128"
    assert parse_candidates("1.1.1.1:80", protocol="https")[0].protocol == "http"


def test_json_documents_extract_nested_records_and_per_record_protocols():
    from proxyharbor.parsing import parse_candidates

    document = """{"data": [
        {"ip": "8.8.8.8", "port": "8080", "protocols": ["http", "socks5"]},
        {"host": "2606:4700:4700::1111", "port": 1080, "protocol": "socks4"},
        {"proxy": "https://1.1.1.1:443"},
        "http://8.8.8.8:8080", "127.0.0.1:80",
        {"ip": "9.9.9.9", "port": 80, "username": "secret"},
        {"ip": "9.9.9.9", "port": true},
        {"ip": "9.9.9.9", "port": "12.5"}
    ]}"""
    assert [p.url for p in parse_candidates(document, format="json")] == [
        "http://8.8.8.8:8080",
        "socks5://8.8.8.8:8080",
        "socks4://[2606:4700:4700::1111]:1080",
        "http://1.1.1.1:443",
    ]
    assert parse_candidates('{"invalid":', format="json") == []


def test_html_extracts_visible_table_rows_links_and_ignores_scripts():
    from proxyharbor.parsing import parse_candidates

    document = """<html><script>9.9.9.9:80</script><style>8.8.4.4:80</style>
        <table><tr><th>IP</th><th>Port</th><th>Protocol</th></tr>
        <tr><td>8.8.8.8</td><td>3128</td><td>SOCKS5</td></tr>
        <tr><td>10.0.0.1</td><td>80</td><td>HTTP</td></tr></table>
        <a href="socks4://1.1.1.1:1080">proxy</a>
        <pre>http://8.8.4.4:8080<br>https://1.0.0.1:443</pre>
        <a href="http://user:pw@9.9.9.9:80">authenticated</a>
        </html>"""
    assert {p.url for p in parse_candidates(document, format="html")} == {
        "socks5://8.8.8.8:3128",
        "socks4://1.1.1.1:1080",
        "http://8.8.4.4:8080",
        "http://1.0.0.1:443",
    }


def test_csv_extracts_columns_without_reading_credentials_as_public_proxies():
    from proxyharbor.parsing import parse_candidates

    document = (
        "ip,port,protocol,username\n"
        "8.8.8.8,8080,socks5,\n"
        "2606:4700:4700::1111,443,https,\n"
        "9.9.9.9,80,http,secret\n"
        "127.0.0.1,80,http,\n"
    )
    assert [p.url for p in parse_candidates(document, format="csv")] == [
        "socks5://8.8.8.8:8080",
        "http://[2606:4700:4700::1111]:443",
    ]
    assert [p.url for p in parse_candidates("1.1.1.1;1080;socks4\n8.8.4.4;3128;http", format="csv")] == [
        "socks4://1.1.1.1:1080",
        "http://8.8.4.4:3128",
    ]


def test_parser_limits_unique_outputs_and_validates_options():
    from proxyharbor.parsing import parse_candidates

    text = "127.0.0.1:80\n8.8.8.8:80\n8.8.8.8:80\n1.1.1.1:80\n9.9.9.9:80"
    assert len(parse_candidates(text, max_items=2)) == 2
    assert parse_candidates(text, max_items=0) == []
    for kwargs in ({"max_items": -1}, {"max_items": True}, {"format": "xml"}, {"protocol": "ftp"}):
        with pytest.raises(ValueError):
            parse_candidates(text, **kwargs)


def test_shared_results_and_sources_have_contract_defaults():
    from proxyharbor.models import CheckResult, ProxyCandidate, SourceSpec

    candidate = ProxyCandidate("8.8.8.8", 80, "http")
    before = time.time()
    result = CheckResult(candidate, False)
    assert before <= result.checked_at <= time.time()
    assert result.latency_ms is None
    assert result.exit_ip is None
    assert result.error is None
    assert result.supports_https is False
    assert CheckResult(candidate, True, checked_at=123.0).checked_at == 123.0
    source = SourceSpec("feed", "Feed", "https://example.org/proxies.txt")
    assert (source.protocol, source.format, source.enabled) == ("http", "text", True)
