"""Test imports for all service modules."""
try:
    from app.services.storage import get_storage_service
    from app.services.resource_manager import get_resource_manager_service
    from app.services.entra_id import get_entra_id_service
    from app.services.cost import get_cost_service
    from app.services.policy import get_policy_service
    print("All services imported successfully!")
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
