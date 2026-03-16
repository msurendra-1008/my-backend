# my-backend

Django REST Framework backend with JWT authentication, role management, employee management, and a UPA (referral tree) network system.

---

## Tech Stack

- Python / Django + Django REST Framework
- SimpleJWT — access & refresh token auth
- drf-spectacular — OpenAPI / Swagger docs
- SQLite (dev) / PostgreSQL (prod)

---

## API Routes

All v1 routes are prefixed with `/api/v1/`.

Interactive docs available at: `GET /api/docs/`

---

### Authentication — `/api/v1/auth/`

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/api/v1/auth/admin/login/` | Public | Admin / employee login (email or mobile + password) |
| POST | `/api/v1/auth/user/register/` | Public | Register a new UPA user (with optional referral ID) |
| POST | `/api/v1/auth/user/login/` | Public | UPA user login (mobile + password) |
| POST | `/api/v1/auth/logout/` | JWT | Blacklist refresh token (logout) |
| GET | `/api/v1/auth/me/` | JWT | Get currently logged-in user profile |
| PATCH | `/api/v1/auth/me/` | JWT | Update currently logged-in user profile |
| PATCH | `/api/v1/auth/me/photo/` | JWT | Upload profile photo |
| POST | `/api/v1/auth/token/refresh/` | Public | Refresh access token using refresh token |

#### UPA Register — request body

```json
{
  "name": "John Doe",
  "mobile": "9876543210",
  "password": "secret123",
  "upa_ref_id": "UPA-XXXXXX",
  "add_standalone": false
}
```

- `upa_ref_id` — optional referral ID of sponsor
- `add_standalone: true` — skip tree placement, register as root node

#### UPA Register — responses

- `201` — Success: `{ success, access, refresh, user }`
- `200` — No vacant leg: `{ success: false, suggest_standalone: true, message }`

---

### Employees — `/api/v1/employees/`

Admin / superadmin only.

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/employees/` | List all employees |
| POST | `/api/v1/employees/` | Create a new employee |
| GET | `/api/v1/employees/{id}/` | Retrieve employee details |
| PATCH | `/api/v1/employees/{id}/` | Update employee (name, department, permissions, status) |

---

### UPA Users — `/api/v1/upa-users/`

Admin / superadmin only. Read-only.

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/upa-users/` | List all UPA members (with leg, parent, wallet info) |
| GET | `/api/v1/upa-users/{id}/` | Retrieve a single UPA member |
| GET | `/api/v1/upa-users/stats/` | Summary stats: `{ total, standalone, networked }` |

---

### Django Admin

Available at `/admin/` — includes the full UPA tree section:

- **UPA Tree** list: UPA ID, name, mobile, parent, leg, depth level
- **Detail view** shows:
  - Parent info panel (name, UPA ID, mobile, which leg this user is placed in)
  - Leg Occupancy panel (L / M / R cards — filled with child info or shown as vacant)
  - Children inline table (all direct referrals of this user)

---

## User Roles

| Role | Description |
|------|-------------|
| `superadmin` | Full access to everything |
| `admin` | Manage employees and view UPA tree |
| `employee` | Limited access based on permissions |
| `upa_user` | End user in the referral network |

---

## UPA Tree Logic

- Every UPA user is placed in a parent's **Left (L)**, **Middle (M)**, or **Right (R)** leg — filled in that order (first available).
- A user with no referral ID is registered as a **standalone / root** node (`parent_user = null`).
- Once all 3 legs are occupied the system returns `suggest_standalone: true` to the frontend.

---

## Running Locally

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
