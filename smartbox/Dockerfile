FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --only-binary=:all: --upgrade pip==26.3 setuptools==84.2.1 wheel==0.46.3
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

WORKDIR /app

# Kopiera in requirements och installera dem
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiera in alla dina nya .py-filer
COPY *.py .
# drivers/-paketet (EnergyWizard Open: bil/laddare/värmepump/sol/spa-gränssnitt) missades
# tidigare av *.py-mönstret ovan (matchar bara toppnivåfiler) - house_config.py importerar
# från det, så utan den här raden kraschar importen i produktion (upptäckt vid Steg 3).
COPY drivers/ ./drivers/
# Sourcefuls FTW-drivrutiner (driver: ftw, lua_host.py) och översättningarna (notisernas språk)
COPY ftw_drivers/ ./ftw_drivers/
# Licensen följer med bilden (AGPL-3.0, #231); FTW-drivrutinernas upstream-licens och notiser ligger i ftw_drivers/
COPY LICENSE ./LICENSE
COPY i18n/ ./i18n/

# Livstecken: huvudloopen skriver /tmp/ew_heartbeat.json varje varv (heartbeat.py). Röd efter tio minuter utan, så att en
# motor som hänger sig syns i docker ps och Portainer. Bara en markering: ingenting startas om av den.
HEALTHCHECK --interval=60s --timeout=10s --start-period=300s --retries=3 CMD ["python", "/app/heartbeat.py"]

# Kör hjärnan (unbuffered så loggarna syns direkt)
CMD ["python", "-u", "main.py"]