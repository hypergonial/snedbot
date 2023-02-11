deploy:
	git pull
	docker compose up -d --build

clean:
	docker compose down
	docker system prune --filter label=snedbot-sned -a