from __future__ import annotations

import autoclaw.persistence as persistence
import autoclaw.persistence.models as persistence_models
import autoclaw.persistence.models.runtime as runtime_models
from autoclaw.persistence import session as persistence_session

REMOVED_MODEL_NAMES = {
    "BudgetCounterModel",
    "ContextItemModel",
    "ContextSpaceModel",
    "DispatchContinuityStateModel",
    "DispatchDeliveryStateModel",
    "DispatchWatchdogStateModel",
    "FlowWaitStateModel",
    "ManifestRootModel",
    "NodeSessionModel",
    "PendingHumanRequestModel",
    "ProviderEventRecordModel",
    "TaskResourceBindingModel",
    "WorkspaceRootLeaseModel",
    "WorkspaceRootModel",
}


def test_persistence_owner_shells_reexport_one_model_identity() -> None:
    for model_name in runtime_models.__all__:
        runtime_model = getattr(runtime_models, model_name)
        assert getattr(persistence_models, model_name) is runtime_model
        assert getattr(persistence, model_name) is runtime_model


def test_removed_runtime_models_have_no_compatibility_export() -> None:
    for module in (persistence, persistence_models, runtime_models):
        assert set(module.__all__).isdisjoint(REMOVED_MODEL_NAMES)
        assert all(not hasattr(module, name) for name in REMOVED_MODEL_NAMES)


def test_reset_only_schema_seams_stay_public_and_no_upgrade_seam_exists() -> None:
    assert {
        "create_empty_database_schema",
        "ensure_database_schema",
        "verify_database_schema",
    } <= set(persistence_session.__all__)
    assert not hasattr(persistence_session, "upgrade_database_schema")
    assert not hasattr(persistence_session, "repair_database_schema")
