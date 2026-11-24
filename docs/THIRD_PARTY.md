# Сторонние компоненты

Для локальной страницы `/docs` включён **swagger-ui-dist 5.36.0** из официального npm registry. JavaScript и CSS обслуживаются самим Proxy Harbor; CDN и подключение к Интернету для отображения документации не требуются.

- Пакет: https://www.npmjs.com/package/swagger-ui-dist
- Архив: https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.36.0.tgz
- Лицензия Apache-2.0: `proxyharbor/static/vendor/LICENSE`.
- Контрольные суммы файлов и проверенный npm integrity: `docs/swagger-vendor.json`.

Python-зависимости устанавливаются в `.venv`, а не включаются в распространяемый исходный архив. Точный набор проверенных версий указан в `requirements-lock.txt`; лицензии библиотек сохраняются в установленных пакетах.
