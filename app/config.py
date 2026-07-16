from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Infra Controller"
    database_url: str = "postgresql+asyncpg://infra:infra@localhost:5432/infra_controller"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    redfish_default_timeout: int = 30
    redfish_verify_ssl: bool = False
    discovery_subnet_timeout: int = 5
    workflow_poll_interval: int = 10
    max_concurrent_workflows: int = 10
    ansible_enabled: bool = False
    ansible_playbook_dir: str = "./playbooks"

    # Auth mode: "none" (open), "entra_id" (Azure AD), "local" (username/password)
    auth_mode: str = "none"

    # Entra ID (Azure AD) settings
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_audience: str = ""

    # RBAC role mappings — Entra ID group Object IDs → app roles
    entra_role_admin: str = ""
    entra_role_operator: str = ""
    entra_role_viewer: str = ""

    # Red Hat Satellite
    satellite_enabled: bool = False
    satellite_url: str = ""
    satellite_username: str = ""
    satellite_password: str = ""
    satellite_org_id: int = 1
    satellite_location_id: int = 1
    satellite_verify_ssl: bool = True

    # Microsoft MECM (formerly SCCM)
    mecm_enabled: bool = False
    mecm_url: str = ""
    mecm_client_id: str = ""
    mecm_client_secret: str = ""
    mecm_tenant_id: str = ""
    mecm_site_code: str = ""

    # VMware vCenter
    vcenter_enabled: bool = False
    vcenter_url: str = ""
    vcenter_username: str = ""
    vcenter_password: str = ""
    vcenter_datacenter: str = ""
    vcenter_cluster: str = ""
    vcenter_verify_ssl: bool = True

    # Ignition (CoreOS/Flatcar) — always available, no external dependency
    ignition_serve_dir: str = "./ignition-configs"

    # Provisioning callback
    callback_base_url: str = "http://localhost:8000"

    model_config = {"env_prefix": "IC_"}


settings = Settings()
