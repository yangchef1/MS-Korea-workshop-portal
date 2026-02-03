# Azure Workshop Management Portal

A full-stack web application for managing Azure workshops at Microsoft Korea Cloud & AI Team. Automates user provisioning, resource setup, and cleanup for customer engineer training sessions.

## Features

- **Workshop Management**: Create and manage Azure workshops with multiple participants
- **Automated Provisioning**:
  - Microsoft Entra ID user creation with temporary passwords
  - Resource group setup for each participant
  - ARM template deployment
  - Azure Policy assignment (region and service restrictions)
- **Cost Tracking**: Real-time cost monitoring via Azure Cost Management API
- **Automated Cleanup**: Azure Function automatically deletes expired workshops
- **Stateless Architecture**: All metadata stored in Azure Blob Storage (no database required)

## Tech Stack

### Backend
- **Python 3.11+**
- **FastAPI** - Modern web framework with OpenAPI support
- **JWT Validation** - Entra ID token validation (PKCE flow)
- **Azure SDK** - Azure resource management
- **Microsoft Graph SDK** - Entra ID user management

### Frontend
- **React 18** - Modern UI library
- **TypeScript** - Type-safe JavaScript
- **Vite** - Fast build tool
- **TanStack Router** - Type-safe routing
- **TanStack Query** - Data fetching and caching
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - High-quality UI components

### Azure Services
- Microsoft Entra ID
- Azure Resource Manager
- Azure Blob Storage
- Azure Policy
- Azure Cost Management
- Azure Functions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │ React SPA   │  │  API Routes  │  │  Azure Services │   │
│  │  (Static)   │  │  (REST API)  │  │   Integration   │   │
│  └─────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    ┌────▼────┐      ┌──────▼──────┐   ┌──────▼──────┐
    │ Azure   │      │   Azure     │   │   Azure     │
    │ Blob    │      │   AD        │   │  Resource   │
    │ Storage │      │ (Entra ID)  │   │  Manager    │
    └─────────┘      └─────────────┘   └─────────────┘
         │
    ┌────▼────────┐
    │  Azure      │  Daily at 2 AM KST
    │  Function   │  (Cleanup expired workshops)
    │  (Timer)    │
    └─────────────┘
```

## Project Structure

```
MS-workshop-portal/
├── backend/                    # FastAPI Backend
│   ├── app/
│   │   ├── main.py             # Application entry point
│   │   ├── config.py           # Configuration settings
│   │   ├── models.py           # Pydantic models
│   │   ├── api/                # REST API endpoints
│   │   │   ├── auth.py         # Auth API (/api/auth/*)
│   │   │   └── workshops.py    # Workshop API (/api/workshops/*)
│   │   ├── services/           # Azure service integrations
│   │   │   ├── cost.py         # Cost Management service
│   │   │   ├── credential.py   # Azure credential management
│   │   │   ├── email.py        # Email service (ACS/SMTP)
│   │   │   ├── entra_id.py     # Entra ID user management
│   │   │   ├── jwt_validator.py # JWT token validation
│   │   │   ├── policy.py       # Azure Policy service
│   │   │   ├── resource_manager.py # Resource Manager service
│   │   │   └── storage.py      # Blob Storage service
│   │   ├── exceptions/         # Custom exception classes
│   │   │   ├── base.py         # Base exception classes
│   │   │   ├── azure.py        # Azure service exceptions
│   │   │   └── validation.py   # Input validation exceptions
│   │   ├── core/               # Dependency injection
│   │   │   └── deps.py         # Service dependencies
│   │   ├── middleware/         # Auth middleware (JWT)
│   │   │   └── auth.py         # JWT authentication middleware
│   │   └── utils/              # Utilities
│   │       ├── csv_parser.py   # CSV parsing for participants
│   │       └── password_generator.py # Secure password generation
│   ├── requirements.txt
│   └── .env.example
├── frontend/                   # React Frontend
│   ├── src/
│   │   ├── main.tsx            # Application entry point
│   │   ├── routes/             # TanStack Router pages
│   │   │   ├── __root.tsx      # Root layout
│   │   │   ├── _layout.tsx     # Main layout with sidebar
│   │   │   ├── login.tsx       # Login page
│   │   │   └── _layout/        # Protected routes
│   │   │       ├── index.tsx   # Dashboard
│   │   │       └── workshops/  # Workshop pages
│   │   │           ├── create.tsx      # Create workshop
│   │   │           └── $workshopId.tsx # Workshop detail
│   │   ├── client/             # API client (axios)
│   │   ├── components/         # UI components
│   │   │   ├── Auth/           # MSAL authentication
│   │   │   ├── Common/         # Common components
│   │   │   ├── Sidebar/        # Navigation sidebar
│   │   │   └── ui/             # shadcn/ui components
│   │   ├── hooks/              # Custom React hooks
│   │   └── lib/                # Utilities
│   │       ├── msalConfig.ts   # MSAL configuration
│   │       └── utils.ts        # Helper functions
│   ├── package.json
│   ├── vite.config.ts
│   └── .env.example
├── arm-templates/              # ARM templates
│   ├── compute-basic.json
│   ├── vnet-basic.json
│   └── vnet-advanced.json
├── function/                   # Azure Function (cleanup)
│   ├── function_app.py         # Timer trigger function
│   ├── host.json
│   └── requirements.txt
├── Dockerfile                  # Multi-stage Docker build
└── README.md
```

## Setup Instructions

### Prerequisites

- Python 3.11 or higher
- Node.js 18+ (for frontend)
- Azure Subscription with appropriate permissions:
  - User Administrator (for Entra ID)
  - Contributor (for Resource Groups)
  - Policy Contributor (for Azure Policies)
  - Cost Management Reader (for cost queries)
- Azure CLI

### 1. Clone Repository

```bash
git clone <repository-url>
cd MS-workshop-portal
```

### 2. Setup Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Setup Frontend

```bash
cd frontend
npm install
```

### 4. Configure Entra ID App Registration

1. Go to Azure Portal → Microsoft Entra ID → App registrations
2. Create a new registration:
   - Name: "Workshop Portal"
   - Supported account types: Single tenant
   - Redirect URI: `http://localhost:5173` (SPA)
3. Note the Application (client) ID
4. Enable PKCE flow (no client secret needed for frontend)

### 5. Configure Environment Variables

**Backend:**
```bash
cd backend
cp .env.example .env
```

Edit `backend/.env` with your Azure credentials:

```env
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_DOMAIN=yourdomain.onmicrosoft.com
AZURE_SUBSCRIPTION_ID=your-subscription-id
BLOB_STORAGE_ACCOUNT=your-storage-account
BLOB_CONTAINER_NAME=workshop-data
USE_AZURE_CLI_CREDENTIAL=true  # For local development
SESSION_SECRET_KEY=your-secret-key
```

**Frontend:**
```bash
cd frontend
cp .env.example .env
```

Edit `frontend/.env`:

```env
VITE_AZURE_CLIENT_ID=your-client-id
VITE_AZURE_TENANT_ID=your-tenant-id
VITE_AZURE_REDIRECT_URI=http://localhost:5173
```

### 6. Run Development Servers

**Backend (Terminal 1):**
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

**Frontend (Terminal 2):**
```bash
cd frontend
npm run dev
```

- Backend API: http://localhost:8000
- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs

### 7. Run Application

**Production Mode:**
```bash
# Build frontend first
cd frontend && npm run build && cd ..

# Run FastAPI (serves both API and frontend)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Development Mode (with hot reload):**
```bash
# Terminal 1: Backend
uvicorn app.main:app --reload

# Terminal 2: Frontend (Vite dev server with proxy)
cd frontend
npm run dev
```

Access the portal:
- Production: `http://localhost:8000`
- Development (frontend): `http://localhost:5173`

## Usage

### Creating a Workshop

1. Navigate to the home page
2. Click "Create Workshop"
3. Fill in workshop details:
   - Name
   - Start and end dates
   - Upload participants CSV (format: `alias` column)
   - Select ARM template
   - Choose allowed regions and services
4. Click "Create Workshop"

The system will:
- Create Entra ID users with temporary passwords
- Create resource groups for each participant
- Deploy ARM templates
- Assign RBAC roles
- Apply Azure Policies

### Viewing Workshop Details

1. Click on a workshop card
2. View participant information
3. Download passwords CSV
4. Monitor costs

### Deleting a Workshop

1. Go to workshop detail page
2. Click "Delete Workshop"
3. Confirm deletion

This will:
- Delete all resource groups
- Delete Entra ID users
- Remove policies
- Delete metadata

1. **Authentication**: MSAL.js with PKCE flow (no client secret on frontend)
2. **Token Validation**: Backend validates JWT Bearer tokens from Entra ID
3. **RBAC**: Use least-privilege principle for managed identity
4. **Secrets**: Never commit `.env` or credentials to git
5. **Input Validation**: All user inputs are validated via Pydantic models
6. **HTTPS**: Always use HTTPS in production (enforced by Azure App Service)

## Monitoring

- Application logs: Check Azure App Service logs
- Function logs: Check Azure Function logs
- Cost tracking: Built-in via Cost Management API
- Resource cleanup: Verify Function runs daily at 2 AM KST

## Troubleshooting

### Common Issues

**Issue: Authentication errors with Entra ID**
- Ensure managed identity has User Administrator role
- Check AZURE_TENANT_ID and AZURE_CLIENT_ID are correct
- Verify the app registration has correct redirect URIs

**Issue: Resource group creation fails**
- Verify Contributor role on subscription
- Check allowed regions match Azure availability

**Issue: Cost data not showing**
- Ensure Cost Management Reader role is assigned
- Cost data may take 24-48 hours to appear for new resources

**Issue: Function not deleting workshops**
- Check function timer trigger settings
- Verify function has access to blob storage and subscription

## Development

### Adding New ARM Templates

1. Create ARM template JSON in `arm-templates/`
2. Upload to blob storage under `templates/`
3. Template automatically appears in UI

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio pytest-cov

# Run tests
pytest

# With coverage
pytest --cov=app
```