# レポート自動生成 CI/CD 実装計画

> **エージェント向け:** 必須サブスキル: superpowers:subagent-driven-development（推奨）または superpowers:executing-plans を使用して、タスクごとに実装してください。

**目標:** レポート自動生成パイプラインの Docker イメージビルド・プッシュを CI/CD で自動化する。

**アーキテクチャ:** BirdXplorer リポの既存 ETL デプロイワークフローに report-generator を追加。BirdXplorer_kouchou-ai リポに ECR プッシュ専用ワークフローを新規作成。

**技術スタック:** GitHub Actions, Docker, AWS ECR, AWS CDK

---

## ファイルマップ

| リポ | ファイル | 操作 | 内容 |
|------|---------|------|------|
| BirdXplorer | `etl/Dockerfile.report_generator` | 移動 | ルートから etl/ 配下に移動（既存パターンに合わせる） |
| BirdXplorer | `.github/workflows/deploy-etl-lambda.yml` | 変更 | マトリクスに report_generator を追加 |
| BirdXplorer_kouchou-ai | `.github/workflows/build-ecr.yml` | 新規 | main プッシュ時に2イメージを ECR にプッシュ |

---

### タスク 1: Dockerfile を etl/ 配下に移動

**ファイル:**
- 移動: `Dockerfile.report-generator` → `etl/Dockerfile.report_generator`

- [ ] **ステップ 1: Dockerfile を移動し、既存パターンに合わせて修正**

既存 ETL の Dockerfile は `etl/` 配下にあり、context はリポルート (`./`) でビルドされる。
`Dockerfile.report-generator` を `etl/Dockerfile.report_generator` に移動。

ファイル名のハイフンをアンダースコアに変更（既存 Dockerfile の命名規則に合わせる）。

内容は context がルートであることを前提に修正:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY README.md /app/README.md
COPY common/ /app/common/
COPY etl/ /app/etl/

RUN pip install --no-cache-dir /app/common /app/etl

CMD ["python", "-m", "birdxplorer_etl.scripts.report_generator"]
```

- [ ] **ステップ 2: 旧 Dockerfile を削除**

```bash
rm Dockerfile.report-generator
```

- [ ] **ステップ 3: ビルドテスト**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
docker build -f etl/Dockerfile.report_generator -t report-generator-test .
```

- [ ] **ステップ 4: コミット**

```bash
git add etl/Dockerfile.report_generator
git rm Dockerfile.report-generator
git commit -m "refactor: move Dockerfile.report_generator to etl/ (naming convention)"
```

---

### タスク 2: deploy-etl-lambda.yml にマトリクス追加

**ファイル:**
- 変更: `.github/workflows/deploy-etl-lambda.yml`

- [ ] **ステップ 1: マトリクスに report_generator を追加**

`strategy.matrix.lambda` 配列に以下を追加:

```yaml
          - { dockerfile: Dockerfile.report_generator, repository: birdxplorer-report-generator }
```

- [ ] **ステップ 2: verify-images に追加**

`deploy-cdk` ジョブの `verify-images` に `birdxplorer-report-generator` を追加:

```yaml
      verify-images: >
        birdxplorer-etl,
        birdxplorer-etl-lang,
        birdxplorer-etl-note-transform,
        birdxplorer-etl-topic,
        birdxplorer-etl-postlookup,
        birdxplorer-etl-db-writer,
        birdxplorer-etl-note-status-update,
        birdxplorer-etl-post-transform,
        birdxplorer-report-generator
```

- [ ] **ステップ 3: paths トリガーは変更不要**

既に `etl/**` と `common/**` がトリガー対象なので、`etl/Dockerfile.report_generator` の変更で自動的に発火する。

- [ ] **ステップ 4: コミット**

```bash
git add .github/workflows/deploy-etl-lambda.yml
git commit -m "ci: add report-generator to ETL deploy pipeline"
```

---

### タスク 3: BirdXplorer_kouchou-ai に ECR ビルドワークフロー追加

**ファイル:**
- 新規: `BirdXplorer_kouchou-ai/.github/workflows/build-ecr.yml`

- [ ] **ステップ 1: ワークフロー作成**

```yaml
name: Build and Push to ECR

on:
  push:
    branches: [main]
    paths:
      - 'apps/api/**'
      - 'apps/static-site-builder/**'
      - 'apps/public-viewer/**'
      - 'packages/**'
      - 'pnpm-lock.yaml'
      - '.github/workflows/build-ecr.yml'

permissions:
  id-token: write
  contents: read

jobs:
  build-and-push:
    runs-on: ubuntu-latest

    strategy:
      matrix:
        image:
          - { dockerfile: apps/api/Dockerfile, repository: birdxplorer-kouchou-ai-api }
          - { dockerfile: apps/static-site-builder/Dockerfile, repository: birdxplorer-kouchou-ai-static-builder }

    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ap-northeast-1

      - uses: aws-actions/amazon-ecr-login@v2
        id: login-ecr

      - uses: docker/setup-buildx-action@v3

      - id: tag
        run: |
          sha=$(echo "${{ github.sha }}" | cut -c1-7)
          echo "tag=dev-sha$sha" >> $GITHUB_OUTPUT

      - uses: docker/build-push-action@v5
        with:
          context: ./
          file: ./${{ matrix.image.dockerfile }}
          push: true
          tags: |
            ${{ steps.login-ecr.outputs.registry }}/${{ matrix.image.repository }}:${{ steps.tag.outputs.tag }}
            ${{ steps.login-ecr.outputs.registry }}/${{ matrix.image.repository }}:latest
          platforms: linux/amd64
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: false
```

- [ ] **ステップ 2: コミット（feature/sync-upstream ブランチ上）**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer_kouchou-ai
git checkout feature/sync-upstream
git add .github/workflows/build-ecr.yml
git commit -m "ci: add ECR build workflow for kouchou-ai API and static-builder"
git push origin feature/sync-upstream
```

注意: このワークフローが動作するには、BirdXplorer_kouchou-ai リポの GitHub Settings に `AWS_ROLE_TO_ASSUME` シークレットを設定する必要がある。BirdXplorer リポと同じ IAM ロールを使用可能。

---

### タスク 4: 初回イメージの手動ビルド＆プッシュ

CI/CD が整う前に、CDK デプロイに必要なイメージを手動でプッシュする。

- [ ] **ステップ 1: ECR ログイン**

```bash
aws ecr get-login-password --region ap-northeast-1 --profile birdxplorer | \
  docker login --username AWS --password-stdin 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com
```

- [ ] **ステップ 2: report-generator イメージをビルド＆プッシュ**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
docker build -f etl/Dockerfile.report_generator -t 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com/birdxplorer-report-generator:latest --platform linux/amd64 .
docker push 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com/birdxplorer-report-generator:latest
```

- [ ] **ステップ 3: kouchou-ai-api イメージをビルド＆プッシュ**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer_kouchou-ai
docker build -f apps/api/Dockerfile -t 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com/birdxplorer-kouchou-ai-api:latest --platform linux/amd64 .
docker push 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com/birdxplorer-kouchou-ai-api:latest
```

- [ ] **ステップ 4: static-site-builder イメージをビルド＆プッシュ**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer_kouchou-ai
docker build -f apps/static-site-builder/Dockerfile -t 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com/birdxplorer-kouchou-ai-static-builder:latest --platform linux/amd64 .
docker push 588738601073.dkr.ecr.ap-northeast-1.amazonaws.com/birdxplorer-kouchou-ai-static-builder:latest
```
