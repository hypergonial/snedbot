FROM python:3.10

ARG postgres_version=14

RUN python3.10 -m ensurepip

RUN pip install -U pip

RUN apt-get update && apt-get -y full-upgrade && apt-get install -y lsb-release

RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'

RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -

RUN apt-get update

RUN apt-get install -y postgresql-client-${postgres_version}

COPY requirements.txt .

RUN pip install -U -r requirements.txt uvloop aiodns~=3.0 cchardet~=2.1 Brotli~=1.0 ciso8601~=2.2 && pip cache purge

COPY . .

CMD ["python3.10", "-O", "main.py"]