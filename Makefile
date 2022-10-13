deploy:
	git pull
	docker compose build $1
	docker compose down
	docker compose up -d

clean:
	docker compose down
	docker system prune --filter label=snedbot-sned -a