import { WorkflowApiClient } from "../api/client";
import { OperatorApiClient } from "../features/operator/operator-api";

export const workflowApi = new WorkflowApiClient();
export const operatorApi = new OperatorApiClient();
