.PHONY: check deploy-up deploy-down deploy-logs deploy-restart deploy-update

check:
	python3 -m unittest discover -s tests
	cd frontend && npm run lint && npm run build

deploy-up:
	docker compose up -d --build

deploy-down:
	docker compose down

deploy-logs:
	docker compose logs -f

deploy-restart:
	docker compose restart

deploy-update:
	git pull
	docker compose up -d --build
	docker image prune -f
