import { ChevronDown, ChevronRight, Circle } from "lucide-react";
import {
    useEffect,
    useMemo,
    useRef,
    useState,
    type KeyboardEvent,
} from "react";

import type { NormalizedMember } from "../../../api/types";
import { Button } from "../../../components/ui";
import { flattenVisibleTeam, type VisibleTeamMember } from "./team-layout";
import { memberTitle } from "./member-presentation";

export interface TeamOutlineProps {
    readonly collapsedMemberIds: ReadonlySet<string>;
    readonly disabled: boolean;
    readonly lead: NormalizedMember;
    readonly onAddChild: (memberId: string) => void;
    readonly onEdit: (memberId: string) => void;
    readonly onRemove: (memberId: string) => void;
    readonly onSelect: (memberId: string) => void;
    readonly onToggleCollapse: (memberId: string) => void;
    readonly requestedFocus: {
        readonly memberId: string;
        readonly revision: number;
    } | null;
    readonly selectedMemberId: string;
}

export function TeamOutline({
    collapsedMemberIds,
    disabled,
    lead,
    onAddChild,
    onEdit,
    onRemove,
    onSelect,
    onToggleCollapse,
    requestedFocus,
    selectedMemberId,
}: TeamOutlineProps) {
    const visible = useMemo(
        () => flattenVisibleTeam(lead, collapsedMemberIds),
        [collapsedMemberIds, lead],
    );
    const visibleIds = useMemo(
        () => new Set(visible.map((entry) => entry.member.id)),
        [visible],
    );
    const [focusedMemberId, setFocusedMemberId] = useState(selectedMemberId);
    const [handledFocusRevision, setHandledFocusRevision] = useState(0);
    const itemRefs = useRef(new Map<string, HTMLDivElement>());
    const typeahead = useRef("");
    const typeaheadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const requestedMemberId =
        requestedFocus !== null &&
        requestedFocus.revision > handledFocusRevision &&
        visibleIds.has(requestedFocus.memberId)
            ? requestedFocus.memberId
            : null;
    const rovingMemberId =
        requestedMemberId ??
        (visibleIds.has(focusedMemberId)
            ? focusedMemberId
            : visibleIds.has(selectedMemberId)
              ? selectedMemberId
              : lead.id);

    useEffect(() => {
        if (visibleIds.has(focusedMemberId)) {
            return;
        }
        const frame = requestAnimationFrame(() => {
            setFocusedMemberId(
                visibleIds.has(selectedMemberId) ? selectedMemberId : lead.id,
            );
        });
        return () => cancelAnimationFrame(frame);
    }, [focusedMemberId, lead.id, selectedMemberId, visibleIds]);

    useEffect(() => {
        if (
            requestedFocus === null ||
            requestedFocus.revision <= handledFocusRevision ||
            !visibleIds.has(requestedFocus.memberId)
        ) {
            return;
        }
        const frame = requestAnimationFrame(() => {
            setHandledFocusRevision(requestedFocus.revision);
            itemRefs.current.get(requestedFocus.memberId)?.focus();
        });
        return () => cancelAnimationFrame(frame);
    }, [handledFocusRevision, requestedFocus, visibleIds]);

    useEffect(
        () => () => {
            if (typeaheadTimer.current !== null) {
                clearTimeout(typeaheadTimer.current);
            }
        },
        [],
    );

    const moveFocus = (memberId: string): void => {
        setFocusedMemberId(memberId);
        requestAnimationFrame(() => itemRefs.current.get(memberId)?.focus());
    };

    const onKeyDown = (
        event: KeyboardEvent<HTMLDivElement>,
        entry: VisibleTeamMember,
    ): void => {
        const index = visible.findIndex(
            (candidate) => candidate.member.id === entry.member.id,
        );
        const children = entry.member.children ?? [];
        const isCollapsed = collapsedMemberIds.has(entry.member.id);

        switch (event.key) {
            case "ArrowDown":
                event.preventDefault();
                moveFocus(
                    visible[Math.min(index + 1, visible.length - 1)]!.member.id,
                );
                return;
            case "ArrowUp":
                event.preventDefault();
                moveFocus(visible[Math.max(index - 1, 0)]!.member.id);
                return;
            case "Home":
                event.preventDefault();
                moveFocus(visible[0]!.member.id);
                return;
            case "End":
                event.preventDefault();
                moveFocus(visible.at(-1)!.member.id);
                return;
            case "ArrowRight":
                if (children.length === 0) {
                    return;
                }
                event.preventDefault();
                if (isCollapsed) {
                    onToggleCollapse(entry.member.id);
                } else {
                    moveFocus(children[0]!.id);
                }
                return;
            case "ArrowLeft":
                event.preventDefault();
                if (children.length > 0 && !isCollapsed) {
                    onToggleCollapse(entry.member.id);
                } else if (entry.parentId !== null) {
                    moveFocus(entry.parentId);
                }
                return;
            case "Enter":
            case " ":
                event.preventDefault();
                onSelect(entry.member.id);
                return;
            default:
                if (
                    event.key.length === 1 &&
                    !event.altKey &&
                    !event.ctrlKey &&
                    !event.metaKey
                ) {
                    event.preventDefault();
                    typeahead.current += event.key.toLocaleLowerCase();
                    if (typeaheadTimer.current !== null) {
                        clearTimeout(typeaheadTimer.current);
                    }
                    typeaheadTimer.current = setTimeout(() => {
                        typeahead.current = "";
                        typeaheadTimer.current = null;
                    }, 700);
                    const match = findTypeaheadMatch(
                        visible,
                        index,
                        typeahead.current,
                    );
                    if (match !== null) {
                        moveFocus(match.member.id);
                    }
                }
        }
    };

    return (
        <aside className="team-outline">
            <div
                aria-label="Workflow team hierarchy"
                className="team-outline__tree"
                role="tree"
            >
                <OutlineBranch
                    collapsedMemberIds={collapsedMemberIds}
                    focusedMemberId={rovingMemberId}
                    itemRefs={itemRefs}
                    member={lead}
                    onFocus={setFocusedMemberId}
                    onKeyDown={onKeyDown}
                    onSelect={onSelect}
                    selectedMemberId={selectedMemberId}
                    visible={visible}
                />
            </div>
            <div
                aria-label={`Actions for ${memberTitle(
                    visible.find(
                        (entry) => entry.member.id === selectedMemberId,
                    )?.member ?? lead,
                )}`}
                className="team-outline__actions"
            >
                <Button
                    disabled={disabled}
                    onClick={() => onAddChild(selectedMemberId)}
                    tone="secondary"
                >
                    Add member
                </Button>
                <Button
                    disabled={disabled}
                    onClick={() => onEdit(selectedMemberId)}
                    tone="quiet"
                >
                    Edit
                </Button>
                <Button
                    disabled={disabled || selectedMemberId === lead.id}
                    onClick={() => onRemove(selectedMemberId)}
                    tone="quiet"
                >
                    Remove
                </Button>
            </div>
        </aside>
    );
}

interface OutlineBranchProps {
    readonly collapsedMemberIds: ReadonlySet<string>;
    readonly focusedMemberId: string;
    readonly itemRefs: React.RefObject<Map<string, HTMLDivElement>>;
    readonly member: NormalizedMember;
    readonly onFocus: (memberId: string) => void;
    readonly onKeyDown: (
        event: KeyboardEvent<HTMLDivElement>,
        entry: VisibleTeamMember,
    ) => void;
    readonly onSelect: (memberId: string) => void;
    readonly selectedMemberId: string;
    readonly visible: readonly VisibleTeamMember[];
}

function OutlineBranch({
    collapsedMemberIds,
    focusedMemberId,
    itemRefs,
    member,
    onFocus,
    onKeyDown,
    onSelect,
    selectedMemberId,
    visible,
}: OutlineBranchProps) {
    const entry = visible.find(
        (candidate) => candidate.member.id === member.id,
    );
    if (entry === undefined) {
        return null;
    }
    const children = member.children ?? [];
    const collapsed = collapsedMemberIds.has(member.id);

    return (
        <div role="none">
            <div
                aria-expanded={children.length === 0 ? undefined : !collapsed}
                aria-level={entry.depth + 1}
                aria-selected={selectedMemberId === member.id}
                className="team-outline__item"
                data-focus-surface="outline"
                data-member-focus={member.id}
                onClick={() => {
                    onFocus(member.id);
                    onSelect(member.id);
                }}
                onFocus={() => onFocus(member.id)}
                onKeyDown={(event) => onKeyDown(event, entry)}
                ref={(element) => {
                    if (element === null) {
                        itemRefs.current?.delete(member.id);
                    } else {
                        itemRefs.current?.set(member.id, element);
                    }
                }}
                role="treeitem"
                tabIndex={focusedMemberId === member.id ? 0 : -1}
            >
                <span aria-hidden="true" className="team-outline__branch-mark">
                    {children.length === 0 ? (
                        <Circle fill="currentColor" size={5} />
                    ) : collapsed ? (
                        <ChevronRight size={14} />
                    ) : (
                        <ChevronDown size={14} />
                    )}
                </span>
                <span>{memberTitle(member)}</span>
            </div>
            {children.length === 0 || collapsed ? null : (
                <div className="team-outline__group" role="group">
                    {children.map((child) => (
                        <OutlineBranch
                            collapsedMemberIds={collapsedMemberIds}
                            focusedMemberId={focusedMemberId}
                            itemRefs={itemRefs}
                            key={child.id}
                            member={child}
                            onFocus={onFocus}
                            onKeyDown={onKeyDown}
                            onSelect={onSelect}
                            selectedMemberId={selectedMemberId}
                            visible={visible}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

function findTypeaheadMatch(
    entries: readonly VisibleTeamMember[],
    currentIndex: number,
    query: string,
): VisibleTeamMember | null {
    const ordered = [
        ...entries.slice(currentIndex + 1),
        ...entries.slice(0, currentIndex + 1),
    ];
    return (
        ordered.find((entry) =>
            memberTitle(entry.member).toLocaleLowerCase().startsWith(query),
        ) ?? null
    );
}
