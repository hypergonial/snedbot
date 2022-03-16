FROM python:3.10

ARG postgres_version=14

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH "$PATH:/root/.local/bin"

RUN apt-get update && apt-get -y full-upgrade && apt-get install -y lsb-release
RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
RUN apt-get update
RUN apt-get install -y postgresql-client-${postgres_version}

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false
RUN poetry install -n --no-dev

COPY . ./
CMD ["python3.10", "-O", "main.py"]