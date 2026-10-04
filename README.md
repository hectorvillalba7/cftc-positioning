# Posicionamiento CFTC

Web estática que sustituye al Excel manual de los reportes de la CFTC. Cada
vez que sale un reporte, GitHub descarga los datos, recalcula la tabla de
cada activo y, si alguna columna de traders o de posiciones supera su máximo
histórico, envía un correo a Gmail.

## Puesta en marcha (una sola vez)

1. **Crea un repositorio** en GitHub y sube el contenido de esta carpeta tal
   cual (incluida la carpeta oculta `.github`). Con repositorio público,
   GitHub Pages es gratis.
2. **Activa la web**: Settings → Pages → Source: "Deploy from a branch" →
   rama `main`, carpeta `/docs`.
3. **Configura el correo**: en tu cuenta de Google activa la verificación en
   dos pasos y crea una "contraseña de aplicación". Después, en el
   repositorio: Settings → Secrets and variables → Actions → New repository
   secret:
   - `GMAIL_USER`: tu dirección de Gmail.
   - `GMAIL_APP_PASSWORD`: la contraseña de aplicación de 16 letras.
   - `MAIL_TO` (opcional): otra dirección de destino. Por defecto, la misma.
4. **Primera carga**: pestaña Actions → "Actualizar datos CFTC" → Run
   workflow. Descarga todo el histórico (desde 2006 en TFF y Disaggregated,
   desde 1986 en Legacy) y tarda unos minutos. La primera carga no envía correo.
5. **Prueba el correo**: Run workflow otra vez marcando "Enviar un correo de
   prueba".
6. Pon la dirección de la web en `notify.site_url` de `config.yaml` para que
   el correo la enlace.

A partir de ahí no hay que hacer nada. El proceso comprueba cuatro veces al
día si hay reporte nuevo; si no lo hay termina en segundos.

## Comprobar que coincide con tu Excel

Tras la primera carga, en local:

    pip install -r requirements.txt openpyxl
    git pull
    python tools/compare_excel.py CFTC_DATA_Tiff.xlsx
    python tools/compare_excel.py CFTC_DATA_Legacy.xlsx --report legacy
    python tools/compare_excel.py CFTC_DATA_Disagreggated.xlsx --report disaggregated

Compara celda a celda las semanas que tenías apuntadas. Si aparecen
diferencias en todas las filas de posiciones, casi seguro que tu Excel usa
el reporte de futuros + opciones: cambia `variant: combined` en
`config.yaml`.

## Cómo se calculan las cosas

- **Inversión**: los activos con `invert: true` cruzan largos y cortos
  (traders, posiciones y % de open interest) antes de cualquier cálculo.
- **Mín / Máx**: de todo el histórico disponible, por columna.
- **Máximos superados**: una semana se anota cuando el dato supera el máximo
  de todas las semanas anteriores. Hasta `warmup_until` (por defecto
  2010-01-01) el histórico solo sirve de referencia. Las columnas que
  avisan se eligen en `event_fields`.
- **Festivos y semanas sin reporte**: el aviso no depende del día de la
  semana. Se envía cuando aparece una fecha de datos posterior a la última
  avisada, sea viernes, lunes o varias semanas juntas. Si falta una semana,
  la tabla lo indica con una fila "Sin reporte".
- **Vencimientos de contrato**: se calculan con la regla de cada mercado
  (último día de negociación) y se marcan con una línea y el código del
  contrato (por ejemplo `Z26`, diciembre de 2026) en el primer reporte
  posterior. Las reglas y los meses de cada activo están en `expiries`, en
  `config.yaml`; el cálculo está en `cot/expiry.py`.
- Si Gmail falla, los datos se actualizan igualmente y el correo se
  reintenta en la siguiente ejecución.

## Añadir activos o reportes

Todo está en `config.yaml`:

- **Un activo nuevo**: añade una línea en `assets` con `id`, `name` y el
  código de contrato de la CFTC (`code`). Si un activo cambió de código a lo
  largo de su historia, `code` admite una lista.
- **Un reporte**: se activa o desactiva con `enabled`. Los tres están
  activos: TFF y Legacy con las divisas, Disaggregated con las commodities.
- **Reglas propias por reporte**: dentro de un reporte se pueden poner
  `warmup_until`, `warmup_min_weeks` o `event_fields` para que no use los
  valores generales de `settings`.

Los reportes aparecen en la web como un selector junto al título. Las
columnas de cada uno están definidas en `cot/schemas.py`. Si la API usa otro
nombre para alguna, el registro de la ejecución muestra un aviso "columnas
no encontradas" con las que hay que corregir ahí.

## Estructura

    config.yaml                  activos, reportes y reglas de aviso
    update.py                    descarga, calcula, escribe docs/data y avisa
    cot/schemas.py               columnas de cada tipo de reporte
    cot/fetch.py                 API pública de la CFTC
    cot/compute.py               inversión, mín/máx y máximos superados
    cot/expiry.py                vencimientos de contrato
    cot/notify.py                correo
    docs/index.html              la web
    docs/data/                   datos generados (un JSON por activo)
    tools/compare_excel.py       comparación con el Excel manual
    .github/workflows/update.yml automatización
