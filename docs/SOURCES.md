# Публичные источники

Стартовый каталог содержит **243 feed-URL / 99 publisher-меток**. Полный аудит проверил 296 URL: 243 содержали публичные кандидаты, 53 были недоступны, пусты или не прошли ограничения.

Источник считается доступным после настоящего HTTP fetch и разбора хотя бы одного публичного IP:port. Это **не доказательство работоспособности прокси**: каждый адрес проходит отдельную V2-проверку перед выдачей.

## Что сохраняет аудит

- Исходный и конечный URL, фактический HTTP status и время в UTC.
- Формат, подсказку протокола, количество публичных кандидатов и достижение лимита.
- SHA-256 распакованного тела, размер, длительность и причину ошибки.
- Provenance: реальные registry, README или repository tree, из которых получен URL.

Publisher-метка — GitHub owner или сгруппированный сайт. Разные метки не гарантируют независимость данных: feeds агрегируют и зеркалируют друг друга. Уникальность endpoints защищена SQLite.

Все положительные typed feeds текущего среза включены, в том числе варианты одного publisher. Seed перемежает HTTP/SOCKS4/SOCKS5. HTTPS-ярлыки означают HTTP CONNECT; поддержку TLS проверяет программа, а не название списка.

## Ограничения загрузки

До 10 одновременных запросов, 15 секунд на весь feed, 5 MB распакованного тела, максимум 5 redirects. Public DNS проверяется на реальном соединении и повторно на redirects. Авторизация, CAPTCHA/WAF, paywall и приватные сети не обходятся.

Счётчик ограничен 100000 кандидатами на feed. `candidate_count_limit_reached` сообщает о достижении предела, а не о точном размере более крупного списка.

## Повторить аудит

Остановите приложение и сохраните свой рабочий каталог перед запуском: команда перезаписывает стартовый `sources.json`.

```bash
python -m scripts.audit_sources --input docs/source-audit.json --output docs/source-audit.json --catalog sources.json --concurrency 10 --timeout 15 --batch-size 80 --max-feeds 500
```

Каждый завершённый батч сохраняется атомарно. Неположительные URL остаются в JSON с причиной. Отчёт ниже — срез, не гарантия uptime; после повторного аудита численные показатели следует пересчитать.

GitHub discovery в приложении ограничен по репозиториям, tree nodes, feed attempts и общему времени. В каталог добавляются только проверенные новые URL; 403/429 сообщаются как ошибки доступа/лимита.

## Включённые feeds

| Publisher | Протокол | Формат | URL | Public кандидаты | HTTP |
|---|---|---|---|---:|---:|
| free-proxy-list.net family | http | html | [https://www.us-proxy.org/](https://www.us-proxy.org/) | 196 | 200 |
| free-proxy-list.net family | socks4 | html | [https://www.socks-proxy.net/](https://www.socks-proxy.net/) | 300 | 200 |
| freeproxy.world | http | html | [https://www.freeproxy.world/?page=1](https://www.freeproxy.world/?page=1) | 50 | 200 |
| freeproxy.world | socks5 | html | [https://www.freeproxy.world/?type=socks5&anonymity=&country=&speed=&port=&page=1](https://www.freeproxy.world/?type=socks5&anonymity=&country=&speed=&port=&page=1) | 50 | 200 |
| github:398001 | http | text | [https://raw.githubusercontent.com/398001/ProxysList/main/all_working.txt](https://raw.githubusercontent.com/398001/ProxysList/main/all_working.txt) | 407 | 200 |
| github:398001 | socks4 | text | [https://raw.githubusercontent.com/398001/ProxysList/main/socks4_working.txt](https://raw.githubusercontent.com/398001/ProxysList/main/socks4_working.txt) | 190 | 200 |
| github:398001 | socks5 | text | [https://raw.githubusercontent.com/398001/ProxysList/main/socks5_working.txt](https://raw.githubusercontent.com/398001/ProxysList/main/socks5_working.txt) | 97 | 200 |
| github:abusaeeidx | http | text | [https://raw.githubusercontent.com/abusaeeidx/TazaProxy-Troxy/main/working_proxies.txt](https://raw.githubusercontent.com/abusaeeidx/TazaProxy-Troxy/main/working_proxies.txt) | 500 | 200 |
| github:access-at | socks4 | text | [https://raw.githubusercontent.com/Access-At/proxy-list/main/socks4.txt](https://raw.githubusercontent.com/Access-At/proxy-list/main/socks4.txt) | 169 | 200 |
| github:aliilapro | http | text | [https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/http.txt](https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/http.txt) | 659 | 200 |
| github:aliilapro | socks4 | text | [https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks4.txt](https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks4.txt) | 174 | 200 |
| github:aliilapro | socks5 | text | [https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks5.txt](https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks5.txt) | 466 | 200 |
| github:andigwandi | http | text | [https://raw.githubusercontent.com/andigwandi/free-proxy/main/proxy_list.txt](https://raw.githubusercontent.com/andigwandi/free-proxy/main/proxy_list.txt) | 581 | 200 |
| github:anonym0uswork1221 | http | text | [https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt](https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt) | 6493 | 200 |
| github:anonym0uswork1221 | socks4 | text | [https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt](https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt) | 652 | 200 |
| github:anonym0uswork1221 | socks5 | text | [https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt](https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt) | 5696 | 200 |
| github:anutmagang | http | text | [https://raw.githubusercontent.com/anutmagang/Free-HighQuality-Proxy-Socks/main/results/http.txt](https://raw.githubusercontent.com/anutmagang/Free-HighQuality-Proxy-Socks/main/results/http.txt) | 166 | 200 |
| github:argh94 | http | text | [https://raw.githubusercontent.com/Argh94/Proxy-List/main/HTTP.txt](https://raw.githubusercontent.com/Argh94/Proxy-List/main/HTTP.txt) | 3758 | 200 |
| github:argh94 | socks4 | text | [https://raw.githubusercontent.com/Argh94/Proxy-List/main/SOCKS4.txt](https://raw.githubusercontent.com/Argh94/Proxy-List/main/SOCKS4.txt) | 665 | 200 |
| github:argh94 | socks4 | text | [https://raw.githubusercontent.com/Argh94/ProxyProwler/main/proxy_output/SOCKS4.txt](https://raw.githubusercontent.com/Argh94/ProxyProwler/main/proxy_output/SOCKS4.txt) | 23 | 200 |
| github:argh94 | socks5 | text | [https://raw.githubusercontent.com/Argh94/Proxy-List/main/SOCKS5.txt](https://raw.githubusercontent.com/Argh94/Proxy-List/main/SOCKS5.txt) | 1000 | 200 |
| github:argh94 | socks5 | text | [https://raw.githubusercontent.com/Argh94/ProxyProwler/main/proxy_output/SOCKS5.txt](https://raw.githubusercontent.com/Argh94/ProxyProwler/main/proxy_output/SOCKS5.txt) | 46 | 200 |
| github:azestkingscrown | http | text | [https://raw.githubusercontent.com/azestkingscrown/Free_Proxy_List/main/working_proxies.txt](https://raw.githubusercontent.com/azestkingscrown/Free_Proxy_List/main/working_proxies.txt) | 681 | 200 |
| github:b4mbo-o | http | text | [https://raw.githubusercontent.com/b4mbo-o/Check-Free-Proxy/main/alive_http.txt](https://raw.githubusercontent.com/b4mbo-o/Check-Free-Proxy/main/alive_http.txt) | 35 | 200 |
| github:b4mbo-o | socks4 | text | [https://raw.githubusercontent.com/b4mbo-o/Check-Free-Proxy/main/alive_socks4.txt](https://raw.githubusercontent.com/b4mbo-o/Check-Free-Proxy/main/alive_socks4.txt) | 58 | 200 |
| github:b4mbo-o | socks5 | text | [https://raw.githubusercontent.com/b4mbo-o/Check-Free-Proxy/main/alive_socks5.txt](https://raw.githubusercontent.com/b4mbo-o/Check-Free-Proxy/main/alive_socks5.txt) | 46 | 200 |
| github:berkay-digital | http | text | [https://raw.githubusercontent.com/berkay-digital/Proxy-Scraper/main/proxies.txt](https://raw.githubusercontent.com/berkay-digital/Proxy-Scraper/main/proxies.txt) | 138 | 200 |
| github:bes-js | http | text | [https://raw.githubusercontent.com/Bes-js/public-proxy-list/main/proxies.txt](https://raw.githubusercontent.com/Bes-js/public-proxy-list/main/proxies.txt) | 1803 | 200 |
| github:blacksnowdot0 | http | text | [https://raw.githubusercontent.com/BlacKSnowDot0/Proxy-Pulse/main/all.txt](https://raw.githubusercontent.com/BlacKSnowDot0/Proxy-Pulse/main/all.txt) | 364 | 200 |
| github:blacksnowdot0 | socks4 | text | [https://raw.githubusercontent.com/BlacKSnowDot0/Proxy-Pulse/main/socks4.txt](https://raw.githubusercontent.com/BlacKSnowDot0/Proxy-Pulse/main/socks4.txt) | 174 | 200 |
| github:blacksnowdot0 | socks5 | text | [https://raw.githubusercontent.com/BlacKSnowDot0/Proxy-Pulse/main/socks5.txt](https://raw.githubusercontent.com/BlacKSnowDot0/Proxy-Pulse/main/socks5.txt) | 55 | 200 |
| github:ch4120n | http | text | [https://raw.githubusercontent.com/Ch4120N/Ch4120N-Proxy-List/master/proxies/all.txt](https://raw.githubusercontent.com/Ch4120N/Ch4120N-Proxy-List/master/proxies/all.txt) | 2139 | 200 |
| github:ch4120n | socks4 | text | [https://raw.githubusercontent.com/Ch4120N/Ch4120N-Proxy-List/master/proxies/socks4.txt](https://raw.githubusercontent.com/Ch4120N/Ch4120N-Proxy-List/master/proxies/socks4.txt) | 746 | 200 |
| github:ch4120n | socks5 | text | [https://raw.githubusercontent.com/Ch4120N/Ch4120N-Proxy-List/master/proxies/socks5.txt](https://raw.githubusercontent.com/Ch4120N/Ch4120N-Proxy-List/master/proxies/socks5.txt) | 481 | 200 |
| github:cheagjihvg | http | text | [https://raw.githubusercontent.com/Cheagjihvg/simple-proxylist/main/http.txt](https://raw.githubusercontent.com/Cheagjihvg/simple-proxylist/main/http.txt) | 25306 | 200 |
| github:cheagjihvg | socks4 | text | [https://raw.githubusercontent.com/Cheagjihvg/simple-proxylist/main/socks4.txt](https://raw.githubusercontent.com/Cheagjihvg/simple-proxylist/main/socks4.txt) | 11571 | 200 |
| github:cheagjihvg | socks5 | text | [https://raw.githubusercontent.com/Cheagjihvg/simple-proxylist/main/socks5.txt](https://raw.githubusercontent.com/Cheagjihvg/simple-proxylist/main/socks5.txt) | 13120 | 200 |
| github:chengaopan | http | text | [https://raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/master/list_raw.txt](https://raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/master/list_raw.txt) | 12 | 200 |
| github:ciara-12 | http | text | [https://raw.githubusercontent.com/Ciara-12/PROXY-free/main/http.txt](https://raw.githubusercontent.com/Ciara-12/PROXY-free/main/http.txt) | 1109 | 200 |
| github:ciara-12 | socks4 | text | [https://raw.githubusercontent.com/Ciara-12/PROXY-free/main/socks4.txt](https://raw.githubusercontent.com/Ciara-12/PROXY-free/main/socks4.txt) | 518 | 200 |
| github:ciara-12 | socks5 | text | [https://raw.githubusercontent.com/Ciara-12/PROXY-free/main/socks5.txt](https://raw.githubusercontent.com/Ciara-12/PROXY-free/main/socks5.txt) | 554 | 200 |
| github:claude89757 | http | text | [https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt](https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt) | 100 | 200 |
| github:daisymashiro | http | text | [https://raw.githubusercontent.com/daisymashiro/proxy-free/main/proxy_alive.txt](https://raw.githubusercontent.com/daisymashiro/proxy-free/main/proxy_alive.txt) | 466 | 200 |
| github:databay-labs | http | text | [https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt](https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt) | 6903 | 200 |
| github:databay-labs | socks4 | text | [https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks4.txt](https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks4.txt) | 1232 | 200 |
| github:databay-labs | socks5 | text | [https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks5.txt](https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks5.txt) | 719 | 200 |
| github:dinoz0rg | http | text | [https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/checked_proxies/http.txt](https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/checked_proxies/http.txt) | 1937 | 200 |
| github:dinoz0rg | socks4 | text | [https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/checked_proxies/socks4.txt](https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/checked_proxies/socks4.txt) | 55 | 200 |
| github:dinoz0rg | socks5 | text | [https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/checked_proxies/socks5.txt](https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/checked_proxies/socks5.txt) | 1264 | 200 |
| github:dpangestuw | http | text | [https://raw.githubusercontent.com/dpangestuw/Free-Proxy/main/All_proxies.txt](https://raw.githubusercontent.com/dpangestuw/Free-Proxy/main/All_proxies.txt) | 9036 | 200 |
| github:dpangestuw | socks4 | text | [https://raw.githubusercontent.com/dpangestuw/Free-PROXY/main/socks4_proxies.txt](https://raw.githubusercontent.com/dpangestuw/Free-PROXY/main/socks4_proxies.txt) | 2676 | 200 |
| github:dpangestuw | socks5 | text | [https://raw.githubusercontent.com/dpangestuw/Free-PROXY/main/socks5_proxies.txt](https://raw.githubusercontent.com/dpangestuw/Free-PROXY/main/socks5_proxies.txt) | 2450 | 200 |
| github:edt-pages | http | json | [https://raw.githubusercontent.com/EDT-Pages/Proxy-List/main/data/http.json](https://raw.githubusercontent.com/EDT-Pages/Proxy-List/main/data/http.json) | 662 | 200 |
| github:edt-pages | socks5 | json | [https://raw.githubusercontent.com/EDT-Pages/Proxy-List/main/data/socks5.json](https://raw.githubusercontent.com/EDT-Pages/Proxy-List/main/data/socks5.json) | 441 | 200 |
| github:elliottophellia | http | text | [https://raw.githubusercontent.com/elliottophellia/proxylist/master/results/pmix_checked.txt](https://raw.githubusercontent.com/elliottophellia/proxylist/master/results/pmix_checked.txt) | 1068 | 200 |
| github:elliottophellia | socks4 | text | [https://raw.githubusercontent.com/elliottophellia/proxylist/master/results/socks4/global/socks4_checked.txt](https://raw.githubusercontent.com/elliottophellia/proxylist/master/results/socks4/global/socks4_checked.txt) | 398 | 200 |
| github:elliottophellia | socks5 | text | [https://raw.githubusercontent.com/elliottophellia/proxylist/master/results/socks5/global/socks5_checked.txt](https://raw.githubusercontent.com/elliottophellia/proxylist/master/results/socks5/global/socks5_checked.txt) | 113 | 200 |
| github:ercindedeoglu | http | text | [https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/http.txt](https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/http.txt) | 65749 | 200 |
| github:ercindedeoglu | socks4 | text | [https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks4.txt](https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks4.txt) | 22473 | 200 |
| github:ercindedeoglu | socks5 | text | [https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks5.txt](https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks5.txt) | 30530 | 200 |
| github:ermaozi | http | text | [https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt](https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt) | 13 | 200 |
| github:fmw86 | http | text | [https://raw.githubusercontent.com/fmw86/free-proxy-pool/main/http_alive.txt](https://raw.githubusercontent.com/fmw86/free-proxy-pool/main/http_alive.txt) | 720 | 200 |
| github:fmw86 | socks5 | text | [https://raw.githubusercontent.com/fmw86/free-proxy-pool/main/socks5_alive.txt](https://raw.githubusercontent.com/fmw86/free-proxy-pool/main/socks5_alive.txt) | 378 | 200 |
| github:fusionproxies | http | text | [https://raw.githubusercontent.com/FusionProxies/free-proxy-list/main/proxies/http.txt](https://raw.githubusercontent.com/FusionProxies/free-proxy-list/main/proxies/http.txt) | 2503 | 200 |
| github:fusionproxies | socks4 | text | [https://raw.githubusercontent.com/FusionProxies/free-proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/FusionProxies/free-proxy-list/main/proxies/socks4.txt) | 661 | 200 |
| github:fusionproxies | socks5 | text | [https://raw.githubusercontent.com/FusionProxies/free-proxy-list/main/proxies/socks5.txt](https://raw.githubusercontent.com/FusionProxies/free-proxy-list/main/proxies/socks5.txt) | 1042 | 200 |
| github:fyvri | http | text | [https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/http.txt](https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/http.txt) | 100000 | 200 |
| github:fyvri | socks4 | text | [https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/socks4.txt](https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/socks4.txt) | 100000 | 200 |
| github:fyvri | socks5 | text | [https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/socks5.txt](https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/socks5.txt) | 100000 | 200 |
| github:gnxd3rftt2we | socks4 | text | [https://raw.githubusercontent.com/gnxD3RfTT2WE/github-proxy-list/main/socks4.txt](https://raw.githubusercontent.com/gnxD3RfTT2WE/github-proxy-list/main/socks4.txt) | 156 | 200 |
| github:gnxd3rftt2we | socks5 | text | [https://raw.githubusercontent.com/gnxD3RfTT2WE/bulk-socks-proxy-list/main/socks5.txt](https://raw.githubusercontent.com/gnxD3RfTT2WE/bulk-socks-proxy-list/main/socks5.txt) | 500 | 200 |
| github:gnxd3rftt2we | socks5 | text | [https://raw.githubusercontent.com/gnxD3RfTT2WE/proxy-list-plain-text/main/socks5.txt](https://raw.githubusercontent.com/gnxD3RfTT2WE/proxy-list-plain-text/main/socks5.txt) | 500 | 200 |
| github:handeveloper1 | http | text | [https://raw.githubusercontent.com/handeveloper1/DailyProxy---Auto-Update-List/main/Proxy-mzyui/http.txt](https://raw.githubusercontent.com/handeveloper1/DailyProxy---Auto-Update-List/main/Proxy-mzyui/http.txt) | 63784 | 200 |
| github:handeveloper1 | socks4 | text | [https://raw.githubusercontent.com/handeveloper1/DailyProxy---Auto-Update-List/main/Proxies-Ercin/socks4.txt](https://raw.githubusercontent.com/handeveloper1/DailyProxy---Auto-Update-List/main/Proxies-Ercin/socks4.txt) | 22473 | 200 |
| github:handeveloper1 | socks5 | text | [https://raw.githubusercontent.com/handeveloper1/DailyProxy---Auto-Update-List/main/Proxies-Ercin/socks5.txt](https://raw.githubusercontent.com/handeveloper1/DailyProxy---Auto-Update-List/main/Proxies-Ercin/socks5.txt) | 30530 | 200 |
| github:hookzof | socks5 | text | [https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt](https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt) | 5703 | 200 |
| github:hproxy-com | http | text | [https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/all.txt](https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/all.txt) | 20804 | 200 |
| github:hproxy-com | socks4 | text | [https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks4.txt](https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks4.txt) | 653 | 200 |
| github:hproxy-com | socks5 | text | [https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks5.txt](https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks5.txt) | 416 | 200 |
| github:i-am-unbekannt | http | text | [https://raw.githubusercontent.com/i-am-unbekannt/BLITZPROXY/main/out-files/http.txt](https://raw.githubusercontent.com/i-am-unbekannt/BLITZPROXY/main/out-files/http.txt) | 3737 | 200 |
| github:i-am-unbekannt | socks4 | text | [https://raw.githubusercontent.com/i-am-unbekannt/BLITZPROXY/main/out-files/socks4.txt](https://raw.githubusercontent.com/i-am-unbekannt/BLITZPROXY/main/out-files/socks4.txt) | 2667 | 200 |
| github:i-am-unbekannt | socks5 | text | [https://raw.githubusercontent.com/i-am-unbekannt/BLITZPROXY/main/out-files/socks5.txt](https://raw.githubusercontent.com/i-am-unbekannt/BLITZPROXY/main/out-files/socks5.txt) | 2945 | 200 |
| github:iplocate | http | text | [https://raw.githubusercontent.com/iplocate/free-proxy-list/main/all-proxies.txt](https://raw.githubusercontent.com/iplocate/free-proxy-list/main/all-proxies.txt) | 1243 | 200 |
| github:iplocate | socks4 | text | [https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks4.txt](https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks4.txt) | 104 | 200 |
| github:iplocate | socks5 | text | [https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks5.txt](https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks5.txt) | 451 | 200 |
| github:ipparrot | http | text | [https://raw.githubusercontent.com/IPParrot/proxy_ips/main/proxies/http.txt](https://raw.githubusercontent.com/IPParrot/proxy_ips/main/proxies/http.txt) | 877 | 200 |
| github:ipparrot | socks4 | text | [https://raw.githubusercontent.com/IPParrot/proxy_ips/main/proxies/socks4.txt](https://raw.githubusercontent.com/IPParrot/proxy_ips/main/proxies/socks4.txt) | 589 | 200 |
| github:ipparrot | socks5 | text | [https://raw.githubusercontent.com/IPParrot/proxy_ips/main/proxies/socks5.txt](https://raw.githubusercontent.com/IPParrot/proxy_ips/main/proxies/socks5.txt) | 342 | 200 |
| github:komutan234 | http | text | [https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/http.txt](https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/http.txt) | 3159 | 200 |
| github:komutan234 | socks5 | text | [https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/socks5.txt](https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/socks5.txt) | 2341 | 200 |
| github:krokmazagaga | http | text | [https://raw.githubusercontent.com/krokmazagaga/http-proxy-list/main/http.txt](https://raw.githubusercontent.com/krokmazagaga/http-proxy-list/main/http.txt) | 280 | 200 |
| github:litportnet | http | text | [https://raw.githubusercontent.com/litportnet/free-proxy-list/main/proxies/all.txt](https://raw.githubusercontent.com/litportnet/free-proxy-list/main/proxies/all.txt) | 3229 | 200 |
| github:litportnet | socks4 | text | [https://raw.githubusercontent.com/litportnet/free-proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/litportnet/free-proxy-list/main/proxies/socks4.txt) | 769 | 200 |
| github:litportnet | socks5 | text | [https://raw.githubusercontent.com/litportnet/free-proxy-list/main/proxies/socks5.txt](https://raw.githubusercontent.com/litportnet/free-proxy-list/main/proxies/socks5.txt) | 389 | 200 |
| github:lonekingcode | http | text | [https://raw.githubusercontent.com/LoneKingCode/free-proxy-db/main/proxies/all.txt](https://raw.githubusercontent.com/LoneKingCode/free-proxy-db/main/proxies/all.txt) | 20 | 200 |
| github:lucasjustinudin | http | text | [https://raw.githubusercontent.com/lucasjustinudin/Free-HighQuality-Proxy-Socks/main/output/by_protocol/http.txt](https://raw.githubusercontent.com/lucasjustinudin/Free-HighQuality-Proxy-Socks/main/output/by_protocol/http.txt) | 35 | 200 |
| github:mauricegift | http | json | [https://raw.githubusercontent.com/mauricegift/free-proxies/master/files/http.json](https://raw.githubusercontent.com/mauricegift/free-proxies/master/files/http.json) | 1527 | 200 |
| github:mauricegift | socks4 | json | [https://raw.githubusercontent.com/mauricegift/free-proxies/master/files/socks4.json](https://raw.githubusercontent.com/mauricegift/free-proxies/master/files/socks4.json) | 497 | 200 |
| github:mauricegift | socks5 | json | [https://raw.githubusercontent.com/mauricegift/free-proxies/master/files/socks5.json](https://raw.githubusercontent.com/mauricegift/free-proxies/master/files/socks5.json) | 313 | 200 |
| github:maximilianfeix | http | text | [https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/all.txt](https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/all.txt) | 560 | 200 |
| github:maximilianfeix | socks4 | text | [https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks4.txt](https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks4.txt) | 224 | 200 |
| github:maximilianfeix | socks5 | text | [https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks5.txt](https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks5.txt) | 149 | 200 |
| github:mmpx12 | http | text | [https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt](https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt) | 440 | 200 |
| github:mmpx12 | socks4 | text | [https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt](https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt) | 661 | 200 |
| github:mmpx12 | socks5 | text | [https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt](https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt) | 279 | 200 |
| github:mohammedcha | http | text | [https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/full_proxies/http.txt](https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/full_proxies/http.txt) | 100000 | 200 |
| github:mohammedcha | socks4 | text | [https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/full_proxies/socks4.txt](https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/full_proxies/socks4.txt) | 100000 | 200 |
| github:mohammedcha | socks5 | text | [https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/full_proxies/socks5.txt](https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/full_proxies/socks5.txt) | 100000 | 200 |
| github:monosans | http | text | [https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt](https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt) | 1090 | 200 |
| github:monosans | socks4 | text | [https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt) | 287 | 200 |
| github:monosans | socks5 | text | [https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt](https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt) | 84 | 200 |
| github:morawskidotmy | http | text | [https://raw.githubusercontent.com/morawskidotmy/youtube-proxies/main/youtube-proxies.txt](https://raw.githubusercontent.com/morawskidotmy/youtube-proxies/main/youtube-proxies.txt) | 131 | 200 |
| github:mzyui | http | text | [https://raw.githubusercontent.com/mzyui/proxy-list/main/all.txt](https://raw.githubusercontent.com/mzyui/proxy-list/main/all.txt) | 69726 | 200 |
| github:mzyui | socks4 | text | [https://raw.githubusercontent.com/mzyui/proxy-list/main/socks4.txt](https://raw.githubusercontent.com/mzyui/proxy-list/main/socks4.txt) | 21536 | 200 |
| github:mzyui | socks5 | text | [https://raw.githubusercontent.com/mzyui/proxy-list/main/socks5.txt](https://raw.githubusercontent.com/mzyui/proxy-list/main/socks5.txt) | 23129 | 200 |
| github:nguyenduytan | http | text | [https://raw.githubusercontent.com/nguyenduytan/NDT-Proxy-Scraper/main/http.txt](https://raw.githubusercontent.com/nguyenduytan/NDT-Proxy-Scraper/main/http.txt) | 11807 | 200 |
| github:nguyenduytan | socks4 | text | [https://raw.githubusercontent.com/nguyenduytan/NDT-Proxy-Scraper/main/socks4.txt](https://raw.githubusercontent.com/nguyenduytan/NDT-Proxy-Scraper/main/socks4.txt) | 5597 | 200 |
| github:nguyenduytan | socks5 | text | [https://raw.githubusercontent.com/nguyenduytan/NDT-Proxy-Scraper/main/socks5.txt](https://raw.githubusercontent.com/nguyenduytan/NDT-Proxy-Scraper/main/socks5.txt) | 9513 | 200 |
| github:nikolait | socks4 | text | [https://raw.githubusercontent.com/NikolaiT/free-proxy-list/main/proxies/socks4_working.txt](https://raw.githubusercontent.com/NikolaiT/free-proxy-list/main/proxies/socks4_working.txt) | 416 | 200 |
| github:nikolait | socks5 | text | [https://raw.githubusercontent.com/NikolaiT/free-proxy-list/main/proxies/socks5_working.txt](https://raw.githubusercontent.com/NikolaiT/free-proxy-list/main/proxies/socks5_working.txt) | 229 | 200 |
| github:noctiro | http | text | [https://raw.githubusercontent.com/noctiro/getproxy/master/file/all.txt](https://raw.githubusercontent.com/noctiro/getproxy/master/file/all.txt) | 19144 | 200 |
| github:noctiro | socks4 | text | [https://raw.githubusercontent.com/noctiro/getproxy/master/file/socks4.txt](https://raw.githubusercontent.com/noctiro/getproxy/master/file/socks4.txt) | 3723 | 200 |
| github:noctiro | socks5 | text | [https://raw.githubusercontent.com/noctiro/getproxy/master/file/socks5.txt](https://raw.githubusercontent.com/noctiro/getproxy/master/file/socks5.txt) | 9013 | 200 |
| github:officialputuid | http | text | [https://raw.githubusercontent.com/officialputuid/KangProxy/main/http/http.txt](https://raw.githubusercontent.com/officialputuid/KangProxy/main/http/http.txt) | 965 | 200 |
| github:officialputuid | socks4 | text | [https://raw.githubusercontent.com/officialputuid/KangProxy/main/socks4/socks4.txt](https://raw.githubusercontent.com/officialputuid/KangProxy/main/socks4/socks4.txt) | 858 | 200 |
| github:officialputuid | socks5 | text | [https://raw.githubusercontent.com/officialputuid/KangProxy/main/socks5/socks5.txt](https://raw.githubusercontent.com/officialputuid/KangProxy/main/socks5/socks5.txt) | 584 | 200 |
| github:peasoft | http | text | [https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list_raw.txt](https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list_raw.txt) | 13 | 200 |
| github:proxifly | http | text | [https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt](https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt) | 12324 | 200 |
| github:proxifly | socks4 | text | [https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt](https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt) | 622 | 200 |
| github:proxifly | socks5 | text | [https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt](https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt) | 5709 | 200 |
| github:proxio-io | http | text | [https://raw.githubusercontent.com/proxio-io/proxy-list/main/all.txt](https://raw.githubusercontent.com/proxio-io/proxy-list/main/all.txt) | 12324 | 200 |
| github:proxio-io | socks4 | text | [https://raw.githubusercontent.com/proxio-io/proxy-list/main/socks4.txt](https://raw.githubusercontent.com/proxio-io/proxy-list/main/socks4.txt) | 1363 | 200 |
| github:proxio-io | socks5 | text | [https://raw.githubusercontent.com/proxio-io/proxy-list/main/socks5.txt](https://raw.githubusercontent.com/proxio-io/proxy-list/main/socks5.txt) | 1059 | 200 |
| github:proxmint | http | text | [https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/all.txt](https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/all.txt) | 1301 | 200 |
| github:proxmint | socks4 | text | [https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/socks4.txt) | 610 | 200 |
| github:proxmint | socks5 | text | [https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/socks5.txt](https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/socks5.txt) | 164 | 200 |
| github:proxy-free | http | text | [https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/all.txt](https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/all.txt) | 2063 | 200 |
| github:proxy-free | socks4 | text | [https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/socks4.txt](https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/socks4.txt) | 323 | 200 |
| github:proxy-free | socks5 | text | [https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/socks5.txt](https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/socks5.txt) | 975 | 200 |
| github:proxygenerator1 | http | text | [https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/ALL/ALL.txt](https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/ALL/ALL.txt) | 2381 | 200 |
| github:proxygenerator1 | socks4 | text | [https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/ForAnonymity/elite/socks4.txt](https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/ForAnonymity/elite/socks4.txt) | 194 | 200 |
| github:proxygenerator1 | socks5 | text | [https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/ForAnonymity/elite/socks5.txt](https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/ForAnonymity/elite/socks5.txt) | 128 | 200 |
| github:proxyscrape | http | text | [https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http](https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http) | 924 | 200 |
| github:proxyscrape | socks4 | text | [https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4](https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4) | 187 | 200 |
| github:proxyscrape | socks5 | text | [https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5](https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5) | 687 | 200 |
| github:proxyscraper | http | text | [https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/http.txt](https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/http.txt) | 2764 | 200 |
| github:proxyscraper | socks4 | text | [https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/socks4.txt](https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/socks4.txt) | 2324 | 200 |
| github:proxyscraper | socks5 | text | [https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/socks5.txt](https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/socks5.txt) | 1949 | 200 |
| github:pwnx0 | http | text | [https://raw.githubusercontent.com/pwnx0/proxy/main/proxies/http.txt](https://raw.githubusercontent.com/pwnx0/proxy/main/proxies/http.txt) | 365 | 200 |
| github:pwnx0 | socks4 | text | [https://raw.githubusercontent.com/pwnx0/proxy/main/proxies/socks4.txt](https://raw.githubusercontent.com/pwnx0/proxy/main/proxies/socks4.txt) | 50 | 200 |
| github:pwnx0 | socks5 | text | [https://raw.githubusercontent.com/pwnx0/proxy/main/proxies/socks5.txt](https://raw.githubusercontent.com/pwnx0/proxy/main/proxies/socks5.txt) | 11 | 200 |
| github:pxys-io | http | text | [https://raw.githubusercontent.com/Pxys-io/DailyProxyList/master/working_proxies.txt](https://raw.githubusercontent.com/Pxys-io/DailyProxyList/master/working_proxies.txt) | 2702 | 200 |
| github:relayglass | http | text | [https://raw.githubusercontent.com/relayglass/free-proxy-list/main/protocol/http/http.txt](https://raw.githubusercontent.com/relayglass/free-proxy-list/main/protocol/http/http.txt) | 152 | 200 |
| github:relayglass | socks4 | text | [https://raw.githubusercontent.com/relayglass/free-proxy-list/main/anonymity/elite/socks4/socks4.txt](https://raw.githubusercontent.com/relayglass/free-proxy-list/main/anonymity/elite/socks4/socks4.txt) | 131 | 200 |
| github:relayglass | socks5 | text | [https://raw.githubusercontent.com/relayglass/free-proxy-list/main/anonymity/elite/socks5/socks5.txt](https://raw.githubusercontent.com/relayglass/free-proxy-list/main/anonymity/elite/socks5/socks5.txt) | 114 | 200 |
| github:rianilham28 | http | text | [https://raw.githubusercontent.com/rianilham28/proxian/main/out/proxies.txt](https://raw.githubusercontent.com/rianilham28/proxian/main/out/proxies.txt) | 648 | 200 |
| github:riommo | http | text | [https://raw.githubusercontent.com/RioMMO/ProxyFree/main/HTTP.txt](https://raw.githubusercontent.com/RioMMO/ProxyFree/main/HTTP.txt) | 13474 | 200 |
| github:riommo | socks4 | text | [https://raw.githubusercontent.com/RioMMO/ProxyFree/main/SOCKS4.txt](https://raw.githubusercontent.com/RioMMO/ProxyFree/main/SOCKS4.txt) | 6982 | 200 |
| github:riyoway | http | text | [https://raw.githubusercontent.com/Riyoway/Proxies/master/all.txt](https://raw.githubusercontent.com/Riyoway/Proxies/master/all.txt) | 9492 | 200 |
| github:riyoway | socks4 | text | [https://raw.githubusercontent.com/Riyoway/Proxies/master/socks4.txt](https://raw.githubusercontent.com/Riyoway/Proxies/master/socks4.txt) | 875 | 200 |
| github:riyoway | socks5 | text | [https://raw.githubusercontent.com/Riyoway/Proxies/master/socks5.txt](https://raw.githubusercontent.com/Riyoway/Proxies/master/socks5.txt) | 966 | 200 |
| github:roosterkid | http | text | [https://openproxylist.xyz/http.txt](https://openproxylist.xyz/http.txt) | 6237 | 200 |
| github:roosterkid | socks4 | text | [https://openproxylist.xyz/socks4.txt](https://openproxylist.xyz/socks4.txt) | 4813 | 200 |
| github:roosterkid | socks5 | text | [https://openproxylist.xyz/socks5.txt](https://openproxylist.xyz/socks5.txt) | 8439 | 200 |
| github:sevenworksdev | http | text | [https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/http.txt](https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/http.txt) | 100000 | 200 |
| github:sevenworksdev | socks4 | text | [https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/socks4.txt) | 100000 | 200 |
| github:sevenworksdev | socks5 | text | [https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/socks5.txt](https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/socks5.txt) | 100000 | 200 |
| github:shubhamshendre | http | text | [https://raw.githubusercontent.com/shubhamshendre/Free-Proxies/main/http.txt](https://raw.githubusercontent.com/shubhamshendre/Free-Proxies/main/http.txt) | 1842 | 200 |
| github:shubhamshendre | socks4 | text | [https://raw.githubusercontent.com/shubhamshendre/Free-Proxies/main/socks4.txt](https://raw.githubusercontent.com/shubhamshendre/Free-Proxies/main/socks4.txt) | 684 | 200 |
| github:shubhamshendre | socks5 | text | [https://raw.githubusercontent.com/shubhamshendre/Free-Proxies/main/socks5.txt](https://raw.githubusercontent.com/shubhamshendre/Free-Proxies/main/socks5.txt) | 4003 | 200 |
| github:skillter | http | text | [https://raw.githubusercontent.com/Skillter/ProxyGather/master/proxies/scraped-proxies.txt](https://raw.githubusercontent.com/Skillter/ProxyGather/master/proxies/scraped-proxies.txt) | 29536 | 200 |
| github:skillter | socks4 | text | [https://raw.githubusercontent.com/Skillter/ProxyGather/master/proxies/working-proxies-socks4.txt](https://raw.githubusercontent.com/Skillter/ProxyGather/master/proxies/working-proxies-socks4.txt) | 167 | 200 |
| github:skillter | socks5 | text | [https://raw.githubusercontent.com/Skillter/ProxyGather/master/proxies/working-proxies-socks5.txt](https://raw.githubusercontent.com/Skillter/ProxyGather/master/proxies/working-proxies-socks5.txt) | 277 | 200 |
| github:solispirit | http | text | [https://raw.githubusercontent.com/SoliSpirit/proxy-list/main/http.txt](https://raw.githubusercontent.com/SoliSpirit/proxy-list/main/http.txt) | 100000 | 200 |
| github:solispirit | socks4 | text | [https://raw.githubusercontent.com/SoliSpirit/proxy-list/main/socks4.txt](https://raw.githubusercontent.com/SoliSpirit/proxy-list/main/socks4.txt) | 100000 | 200 |
| github:solispirit | socks5 | text | [https://raw.githubusercontent.com/SoliSpirit/proxy-list/main/socks5.txt](https://raw.githubusercontent.com/SoliSpirit/proxy-list/main/socks5.txt) | 100000 | 200 |
| github:solproxy | http | text | [https://raw.githubusercontent.com/solproxy/sol-free-proxy-list/main/http.txt](https://raw.githubusercontent.com/solproxy/sol-free-proxy-list/main/http.txt) | 105 | 200 |
| github:solproxy | http | text | [https://solproxy.net/free-proxy-list/api.txt](https://solproxy.net/free-proxy-list/api.txt) | 105 | 200 |
| github:stormsia | http | text | [https://raw.githubusercontent.com/stormsia/proxy-list/main/http.txt](https://raw.githubusercontent.com/stormsia/proxy-list/main/http.txt) | 232 | 200 |
| github:stormsia | socks4 | text | [https://raw.githubusercontent.com/stormsia/proxy-list/main/socks4.txt](https://raw.githubusercontent.com/stormsia/proxy-list/main/socks4.txt) | 1 | 200 |
| github:stormsia | socks5 | text | [https://raw.githubusercontent.com/stormsia/proxy-list/main/socks5.txt](https://raw.githubusercontent.com/stormsia/proxy-list/main/socks5.txt) | 348 | 200 |
| github:sunny9577 | http | text | [https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt](https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt) | 500 | 200 |
| github:sunny9577 | http | text | [https://sunny9577.github.io/proxy-scraper/proxies.txt](https://sunny9577.github.io/proxy-scraper/proxies.txt) | 500 | 200 |
| github:sunny9577 | socks4 | text | [https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks4_proxies.txt](https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks4_proxies.txt) | 68 | 200 |
| github:sunny9577 | socks5 | text | [https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks5_proxies.txt](https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks5_proxies.txt) | 138 | 200 |
| github:themiralay | http | text | [https://raw.githubusercontent.com/themiralay/Proxy-List-World/master/data.txt](https://raw.githubusercontent.com/themiralay/Proxy-List-World/master/data.txt) | 222 | 200 |
| github:theriturajps | http | text | [https://raw.githubusercontent.com/theriturajps/proxy-list/main/proxies.txt](https://raw.githubusercontent.com/theriturajps/proxy-list/main/proxies.txt) | 5108 | 200 |
| github:thespeedx | http | text | [https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt](https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt) | 2764 | 200 |
| github:thespeedx | socks4 | text | [https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt](https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt) | 2324 | 200 |
| github:thespeedx | socks5 | text | [https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt](https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt) | 1949 | 200 |
| github:thordata | http | text | [https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/https.txt](https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/https.txt) | 23 | 200 |
| github:thordata | socks4 | text | [https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/socks4.txt) | 44 | 200 |
| github:thordata | socks5 | text | [https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/docs/data/links/socks5.txt](https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/docs/data/links/socks5.txt) | 40 | 200 |
| github:tianndev | http | text | [https://raw.githubusercontent.com/Tianndev/free-proxy/main/proxy/all.txt](https://raw.githubusercontent.com/Tianndev/free-proxy/main/proxy/all.txt) | 30401 | 200 |
| github:tianndev | socks4 | text | [https://raw.githubusercontent.com/Tianndev/free-proxy/main/proxy/socks4.txt](https://raw.githubusercontent.com/Tianndev/free-proxy/main/proxy/socks4.txt) | 3443 | 200 |
| github:tianndev | socks5 | text | [https://raw.githubusercontent.com/Tianndev/free-proxy/main/proxy/socks5.txt](https://raw.githubusercontent.com/Tianndev/free-proxy/main/proxy/socks5.txt) | 2953 | 200 |
| github:trio666 | http | text | [https://raw.githubusercontent.com/trio666/proxy-checker/main/all.txt](https://raw.githubusercontent.com/trio666/proxy-checker/main/all.txt) | 2036 | 200 |
| github:trio666 | socks4 | text | [https://raw.githubusercontent.com/trio666/proxy-checker/main/socks4.txt](https://raw.githubusercontent.com/trio666/proxy-checker/main/socks4.txt) | 270 | 200 |
| github:trio666 | socks5 | text | [https://raw.githubusercontent.com/trio666/proxy-checker/main/socks5.txt](https://raw.githubusercontent.com/trio666/proxy-checker/main/socks5.txt) | 819 | 200 |
| github:tsprnay | http | text | [https://raw.githubusercontent.com/Tsprnay/Proxy-lists/master/proxies/all.txt](https://raw.githubusercontent.com/Tsprnay/Proxy-lists/master/proxies/all.txt) | 100000 | 200 |
| github:tsprnay | socks4 | text | [https://raw.githubusercontent.com/Tsprnay/Proxy-lists/master/proxies/socks4.txt](https://raw.githubusercontent.com/Tsprnay/Proxy-lists/master/proxies/socks4.txt) | 100000 | 200 |
| github:tsprnay | socks5 | text | [https://raw.githubusercontent.com/Tsprnay/Proxy-lists/master/proxies/socks5.txt](https://raw.githubusercontent.com/Tsprnay/Proxy-lists/master/proxies/socks5.txt) | 100000 | 200 |
| github:tuanminpay | http | text | [https://raw.githubusercontent.com/TuanMinPay/live-proxy/master/http.txt](https://raw.githubusercontent.com/TuanMinPay/live-proxy/master/http.txt) | 9026 | 200 |
| github:tuanminpay | socks4 | text | [https://raw.githubusercontent.com/TuanMinPay/live-proxy/master/socks4.txt](https://raw.githubusercontent.com/TuanMinPay/live-proxy/master/socks4.txt) | 6875 | 200 |
| github:tuanminpay | socks5 | text | [https://raw.githubusercontent.com/TuanMinPay/live-proxy/master/socks5.txt](https://raw.githubusercontent.com/TuanMinPay/live-proxy/master/socks5.txt) | 10330 | 200 |
| github:vadim287 | http | text | [https://raw.githubusercontent.com/Vadim287/free-proxy/main/proxies/http.txt](https://raw.githubusercontent.com/Vadim287/free-proxy/main/proxies/http.txt) | 44 | 200 |
| github:vadim287 | socks4 | text | [https://raw.githubusercontent.com/Vadim287/free-proxy/main/proxies/socks4.txt](https://raw.githubusercontent.com/Vadim287/free-proxy/main/proxies/socks4.txt) | 15 | 200 |
| github:vadim287 | socks5 | text | [https://raw.githubusercontent.com/Vadim287/free-proxy/main/proxies/socks5.txt](https://raw.githubusercontent.com/Vadim287/free-proxy/main/proxies/socks5.txt) | 3 | 200 |
| github:vakhov | http | text | [https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt](https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt) | 524 | 200 |
| github:vakhov | socks4 | text | [https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks4.txt](https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks4.txt) | 165 | 200 |
| github:vakhov | socks5 | text | [https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt](https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt) | 21 | 200 |
| github:vann-dev | http | text | [https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/http.txt](https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/http.txt) | 7905 | 200 |
| github:vann-dev | socks4 | text | [https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/socks4.txt](https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/socks4.txt) | 3456 | 200 |
| github:vann-dev | socks5 | text | [https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/socks5.txt](https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/socks5.txt) | 7940 | 200 |
| github:vmheaven | http | text | [https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/http.txt](https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/http.txt) | 4086 | 200 |
| github:vmheaven | socks4 | text | [https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks4.txt](https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks4.txt) | 1519 | 200 |
| github:vmheaven | socks5 | text | [https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks5.txt](https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks5.txt) | 889 | 200 |
| github:volkansah | http | text | [https://raw.githubusercontent.com/VolkanSah/Auto-Proxy-Fetcher/main/proxies.txt](https://raw.githubusercontent.com/VolkanSah/Auto-Proxy-Fetcher/main/proxies.txt) | 500 | 200 |
| github:vpslabcloud | http | text | [https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/all_ssl.txt](https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/all_ssl.txt) | 968 | 200 |
| github:vpslabcloud | socks4 | text | [https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks4_all.txt](https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks4_all.txt) | 158 | 200 |
| github:vpslabcloud | socks5 | text | [https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks5_all.txt](https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks5_all.txt) | 563 | 200 |
| github:watchttvv | http | text | [https://raw.githubusercontent.com/watchttvv/free-proxy-list/main/proxy.txt](https://raw.githubusercontent.com/watchttvv/free-proxy-list/main/proxy.txt) | 18 | 200 |
| github:wyattowalsh | http | text | [https://raw.githubusercontent.com/wyattowalsh/proxywhirl/main/docs/proxy-lists/http.txt](https://raw.githubusercontent.com/wyattowalsh/proxywhirl/main/docs/proxy-lists/http.txt) | 6627 | 200 |
| github:wyattowalsh | socks4 | text | [https://raw.githubusercontent.com/wyattowalsh/proxywhirl/main/docs/proxy-lists/socks4.txt](https://raw.githubusercontent.com/wyattowalsh/proxywhirl/main/docs/proxy-lists/socks4.txt) | 105 | 200 |
| github:wyattowalsh | socks5 | text | [https://raw.githubusercontent.com/wyattowalsh/proxywhirl/main/docs/proxy-lists/socks5.txt](https://raw.githubusercontent.com/wyattowalsh/proxywhirl/main/docs/proxy-lists/socks5.txt) | 929 | 200 |
| github:xigmadev | http | text | [https://raw.githubusercontent.com/XigmaDev/proxy/main/proxies.txt](https://raw.githubusercontent.com/XigmaDev/proxy/main/proxies.txt) | 25 | 200 |
| github:xyzs996 | http | text | [https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/all.txt](https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/all.txt) | 4491 | 200 |
| github:xyzs996 | socks4 | text | [https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/socks4.txt](https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/socks4.txt) | 747 | 200 |
| github:xyzs996 | socks5 | text | [https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/socks5.txt](https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/socks5.txt) | 429 | 200 |
| github:z3a4 | http | text | [https://raw.githubusercontent.com/z3a4/free-proxy-list/main/proxies/unchecked/http-proxies.txt](https://raw.githubusercontent.com/z3a4/free-proxy-list/main/proxies/unchecked/http-proxies.txt) | 3764 | 200 |
| github:z3a4 | socks4 | text | [https://raw.githubusercontent.com/z3a4/free-proxy-list/main/proxies/unchecked/socks4-proxies.txt](https://raw.githubusercontent.com/z3a4/free-proxy-list/main/proxies/unchecked/socks4-proxies.txt) | 3068 | 200 |
| github:z3a4 | socks5 | text | [https://raw.githubusercontent.com/z3a4/free-proxy-list/main/proxies/unchecked/socks5-proxies.txt](https://raw.githubusercontent.com/z3a4/free-proxy-list/main/proxies/unchecked/socks5-proxies.txt) | 3119 | 200 |
| github:zaeem20 | http | text | [https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt](https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt) | 82 | 200 |
| github:zaeem20 | socks4 | text | [https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks4.txt](https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks4.txt) | 38 | 200 |
| github:zaeem20 | socks5 | text | [https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt](https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt) | 63 | 200 |
| proxylist.geonode.com | http | json | [https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc](https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc) | 500 | 200 |
| proxylist.geonode.com | socks4 | json | [https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=speed&sort_type=asc&protocols=socks4](https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=speed&sort_type=asc&protocols=socks4) | 500 | 200 |
| proxylist.geonode.com | socks5 | json | [https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=speed&sort_type=asc&protocols=socks5](https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=speed&sort_type=asc&protocols=socks5) | 500 | 200 |
| proxyspace.pro | http | text | [https://proxyspace.pro/http.txt](https://proxyspace.pro/http.txt) | 3977 | 200 |
| proxyspace.pro | socks4 | text | [https://proxyspace.pro/socks4.txt](https://proxyspace.pro/socks4.txt) | 4750 | 200 |
| proxyspace.pro | socks5 | text | [https://proxyspace.pro/socks5.txt](https://proxyspace.pro/socks5.txt) | 7947 | 200 |
| spys.me | http | text | [https://spys.me/proxy.txt](https://spys.me/proxy.txt) | 400 | 200 |
| spys.me | socks5 | text | [https://spys.me/socks.txt](https://spys.me/socks.txt) | 400 | 200 |

Полный список неуспешных URL и причин: [source-audit.json](source-audit.json). Сумма по feeds не является уникальным размером общего пула.

## Sources

[1] https://raw.githubusercontent.com/maximilianfeix/proxy-scraper/8594ca0c2831f0f8b1a932952eef724c87dcee7f/proxyscraper/sources.json
[2] https://raw.githubusercontent.com/Denisyoya/Proxy-List-Gamt/main/sources/github.txt
[3] https://raw.githubusercontent.com/Denisyoya/Proxy-List-Gamt/main/sources/websites.txt
[4] https://raw.githubusercontent.com/monosans/proxy-scraper-checker/main/config.toml
