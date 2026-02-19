# Infrastructure (Bicep IaC)

Azure Workshop Portal의 인프라를 코드로 관리합니다.

## 구조

```
infra/
├── main.bicep                    # 진입점 (모듈 오케스트레이션)
├── parameters/
│   ├── dev.bicepparam            # 개발 환경 파라미터
│   └── prod.bicepparam           # 운영 환경 파라미터
└── modules/
    ├── container-apps.bicep      # Container Apps Environment + Backend (GHCR)
    ├── static-web-app.bicep      # Static Web App (Free tier)
    ├── storage-account.bicep     # Table Storage (4개 테이블)
    ├── communication.bicep       # Azure Communication Services
    └── function-app.bicep        # Function App (워크샵 클린업)
```

## 배포

### 사전 준비

```bash
# Bicep 문법 확인
wsl az bicep build --file infra/main.bicep

# What-If 프리뷰
wsl az deployment sub create --what-if \
  --location koreacentral \
  --template-file infra/main.bicep \
  --parameters infra/parameters/dev.bicepparam \
  spClientSecret=dummy acsConnectionString=dummy ghcrToken=dummy
```

### GHCR 사전 준비

1. **PAT 생성**: GitHub Settings → Developer settings → Personal access tokens → `read:packages` 권한
2. **GitHub Actions Secret 등록**: Repository Settings → Secrets → `GHCR_TOKEN`에 PAT 등록
3. **패키지 가시성**: GHCR 패키지가 private인 경우 PAT에 `read:packages` 권한 필수

### 배포 실행

```bash
wsl az deployment sub create \
  --location koreacentral \
  --template-file infra/main.bicep \
  --parameters infra/parameters/prod.bicepparam \
  spClientSecret='$SP_CLIENT_SECRET' \
  acsConnectionString='$ACS_CONNECTION_STRING' \
  ghcrToken='$GHCR_TOKEN'
```

## 신규 Subscription 추가 체크리스트

새 Subscription을 워크샵 대상에 추가할 때 반드시 아래 순서대로 진행합니다.

1. **SP 역할 할당**: target Subscription에 `Contributor` 역할 부여
   ```bash
   wsl az role assignment create \
     --assignee <SP_CLIENT_ID> \
     --role "Contributor" \
     --scope "/subscriptions/<NEW_SUB_ID>"
   ```

2. **Graph API 권한 확인**: Tenant가 동일하면 추가 작업 없음

3. **파라미터 업데이트**: `prod.bicepparam`의 `subscriptionIds` 배열에 ID 추가
   ```bicep
   param subscriptionIds = ['existing-sub-id', 'new-sub-id']
   ```

4. **Bicep 배포**: 환경변수 자동 갱신
   ```bash
   wsl az deployment sub create --location koreacentral \
     --template-file infra/main.bicep \
     --parameters infra/parameters/prod.bicepparam \
     spClientSecret='...' acsConnectionString='...' ghcrToken='...'
   ```

5. **CSV에서 사용**: 참가자 CSV에 새 `subscription_id` 사용 가능

## 환경변수 매핑

| 변수 | Container Apps | Function App | 비고 |
|------|---------------|-------------|------|
| `AZURE_SP_SUBSCRIPTION_ID` | ✅ | — | 기본 Subscription (하위 호환) |
| `ALLOWED_SUBSCRIPTION_IDS` | ✅ | ✅ | 콤마 구분, Bicep `join()` |
| `AZURE_SUBSCRIPTION_ID` | — | deprecated | FA 하위 호환 폴백 |
| `ALLOWED_ORIGINS` | ✅ | — | CORS용 |

## Storage Account 멱등성

- `prod.bicepparam`의 `storageAccountName`은 **기존 운영 Storage Account 이름**과 정확히 일치해야 합니다.
- ARM Incremental 배포가 데이터를 보존합니다 (SKU, Location만 일치 필요).
- What-If에서 Storage Account가 `Delete`가 아닌 `NoChange` 또는 `Modify`인지 반드시 확인하세요.
