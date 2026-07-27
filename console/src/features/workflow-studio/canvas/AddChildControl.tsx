import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { LoaderCircle, Plus } from "lucide-react";

export type AddChildNode = Node<AddChildData, "add-child">;

export type AddChildData = {
    readonly disabled: boolean;
    readonly onAdd: (parentMemberId: string) => void;
    readonly parentMemberId: string;
    readonly parentName: string;
    readonly pending: boolean;
} & Record<string, unknown>;

export function AddChildControl({ data }: NodeProps<AddChildNode>) {
    return (
        <div className="team-add-control">
            <Handle
                aria-hidden="true"
                className="team-add-control__handle"
                isConnectable={false}
                position={Position.Left}
                type="target"
            />
            <button
                aria-busy={data.pending || undefined}
                aria-label={`Add child to ${data.parentName}`}
                className="team-add-control__button nodrag nopan"
                disabled={data.disabled}
                onClick={() => data.onAdd(data.parentMemberId)}
                type="button"
            >
                {data.pending ? (
                    <LoaderCircle
                        aria-hidden="true"
                        className="team-add-control__spinner"
                        size={20}
                    />
                ) : (
                    <Plus aria-hidden="true" size={22} />
                )}
            </button>
        </div>
    );
}
