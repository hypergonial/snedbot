FROM python:3.10

RUN python3.10 -m ensurepip

RUN pip install -U pip

RUN apt update && apt full-upgrade

COPY requirements.txt .

RUN pip install -U -r requirements.txt uvloop aiodns~=3.0 cchardet~=2.1 Brotli~=1.0 ciso8601~=2.2 && pip cache purge

COPY . .

CMD ["python3.10", "-O", "main.py"]