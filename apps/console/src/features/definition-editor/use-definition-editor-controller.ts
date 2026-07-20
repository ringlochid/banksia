import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
    useBeforeUnload,
    useBlocker,
    useSearchParams,
    type BlockerFunction,
} from "react-router-dom";

import { getNextCursor, isApiAbortError, type ConsoleErrorView } from "../../api/client";
import { applyDraftBodyIndentation } from "./definition-editor-indent";
import {
    type DraftActionDialog,
    type DraftConfirmation,
    type DraftOperation,
    type NewDraftFormState,
} from "./definition-editor-dialogs";
import {
    createDraft,
    deleteDraft,
    publishDraft as publishDraftRequest,
    readDraft,
    readDrafts,
    replaceDraftWithCurrent,
    saveDraft as saveDraftRequest,
    toErrorView,
    validateDraft as validateDraftRequest,
    type DraftDetail,
    type DraftIdentity,
} from "./definition-editor-data";
import {
    compareDraftSummaryUpdatedAt,
    draftIdentityEquals,
    draftIdentityFromSearch,
    draftIdentityFromSummary,
    draftIdentityKey,
    draftSummaryFromDetail,
    formError,
    initialDetailState,
    initialListState,
    initialNewDraftForm,
    normalizeDraftKey,
    type DraftDetailState,
    type DraftListState,
} from "./definition-editor-model";
import { starterBodyForKind } from "./definition-editor-template";

interface DraftOperationContext {
    readonly generation: number;
    readonly identityKey: string;
}

export interface DefinitionEditorController {
    readonly cancelDraftConfirmation: () => void;
    readonly closeDraftActionDialog: () => void;
    readonly closeNewDraftDialog: () => void;
    readonly confirmDraftAction: () => void;
    readonly createNewDraft: () => void;
    readonly currentDraft: DraftDetail | null;
    readonly detailState: DraftDetailState;
    readonly discardBlockedNavigation: () => void;
    readonly draftActionDialog: DraftActionDialog;
    readonly draftConfirmation: DraftConfirmation | null;
    readonly editorBody: string;
    readonly handleDraftBodyKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
    readonly isBusy: boolean;
    readonly isDirty: boolean;
    readonly isNewDraftBlocked: boolean;
    readonly isOperationNavigationBlocked: boolean;
    readonly isUnsavedNavigationBlocked: boolean;
    readonly keepBlockedNavigation: () => void;
    readonly listState: DraftListState;
    readonly loadMoreDrafts: () => void;
    readonly newDraftForm: NewDraftFormState;
    readonly openDraftConfirmation: (action: DraftConfirmation) => void;
    readonly openNewDraftDialog: () => void;
    readonly operation: DraftOperation;
    readonly operationError: ConsoleErrorView | null;
    readonly publishDraft: () => void;
    readonly refreshList: () => void;
    readonly refreshSelected: () => void;
    readonly saveDraft: () => void;
    readonly selectDraft: (identity: DraftIdentity | null) => void;
    readonly selection: DraftIdentity | null;
    readonly setEditorBody: (body: string) => void;
    readonly setNewDraftForm: (form: NewDraftFormState) => void;
    readonly validateDraft: () => void;
}

export function useDefinitionEditorController(): DefinitionEditorController {
    const [searchParams, setSearchParams] = useSearchParams();
    const routeSelection = useMemo(() => draftIdentityFromSearch(searchParams), [searchParams]);
    const routeSelectionKey = routeSelection === null ? "" : draftIdentityKey(routeSelection);
    const [selection, setSelection] = useState<DraftIdentity | null>(routeSelection);
    const [listState, setListState] = useState<DraftListState>(initialListState);
    const [detailState, setDetailState] = useState<DraftDetailState>(initialDetailState);
    const [editorBody, setEditorBody] = useState("");
    const [newDraftForm, setNewDraftForm] = useState<NewDraftFormState>(initialNewDraftForm);
    const [operation, setOperation] = useState<DraftOperation>(null);
    const [operationError, setOperationError] = useState<ConsoleErrorView | null>(null);
    const [draftActionDialog, setDraftActionDialog] = useState<DraftActionDialog>(null);
    const [draftConfirmation, setDraftConfirmation] = useState<DraftConfirmation | null>(null);
    const [isNewDraftBlocked, setIsNewDraftBlocked] = useState(false);
    const [refreshToken, setRefreshToken] = useState(0);
    const [detailRefreshToken, setDetailRefreshToken] = useState(0);
    const navigationBypassRef = useRef(false);
    const detailReadGenerationRef = useRef(0);
    const listReadGenerationRef = useRef(0);
    const operationGenerationRef = useRef(0);
    const createGenerationRef = useRef(0);
    const selectedIdentityKeyRef = useRef(selection === null ? "" : draftIdentityKey(selection));
    const selectedKey = selection === null ? "" : draftIdentityKey(selection);
    selectedIdentityKeyRef.current = selectedKey;

    const currentDraft = detailState.draft;
    const isDirty = currentDraft !== null && editorBody !== currentDraft.body;
    const isBusy = operation !== null || newDraftForm.isCreating;

    useBeforeUnload(
        useCallback(
            (event) => {
                if (!isDirty && !isBusy) return;
                event.preventDefault();
            },
            [isBusy, isDirty],
        ),
        { capture: true },
    );
    const shouldBlockNavigation = useCallback<BlockerFunction>(
        ({ currentLocation, nextLocation }) =>
            (isDirty || isBusy) &&
            !navigationBypassRef.current &&
            (currentLocation.pathname !== nextLocation.pathname ||
                currentLocation.search !== nextLocation.search ||
                currentLocation.hash !== nextLocation.hash),
        [isBusy, isDirty],
    );
    const navigationBlocker = useBlocker(shouldBlockNavigation);

    const upsertListSummary = useCallback((draft: DraftDetail): void => {
        const summary = draftSummaryFromDetail(draft);
        setListState((currentState) => ({
            ...currentState,
            rows: [
                summary,
                ...currentState.rows.filter(
                    (row) => !draftIdentityEquals(draftIdentityFromSummary(row), summary),
                ),
            ].sort(compareDraftSummaryUpdatedAt),
        }));
    }, []);

    const applyDraftDetail = useCallback(
        (
            draft: DraftDetail,
            {
                clearOutcome = true,
                includeInList = true,
            }: { clearOutcome?: boolean; includeInList?: boolean } = {},
        ): void => {
            setDetailState({ draft, error: null, isLoading: false });
            setEditorBody(draft.body);
            if (clearOutcome) {
                setDraftActionDialog(null);
                setDraftConfirmation(null);
                setOperationError(null);
            }
            if (includeInList) upsertListSummary(draft);
        },
        [upsertListSummary],
    );

    useEffect(() => {
        const defaultSelection =
            listState.rows.length === 0 ? null : draftIdentityFromSummary(listState.rows[0]);
        setSelection((currentSelection) => {
            const nextSelection = routeSelection ?? currentSelection ?? defaultSelection;
            if (draftIdentityEquals(currentSelection, nextSelection)) return currentSelection;
            selectedIdentityKeyRef.current =
                nextSelection === null ? "" : draftIdentityKey(nextSelection);
            return nextSelection;
        });
    }, [listState.rows, routeSelection, routeSelectionKey]);

    useEffect(() => {
        const abortController = new AbortController();
        const generation = listReadGenerationRef.current + 1;
        listReadGenerationRef.current = generation;
        setListState((currentState) => ({ ...currentState, error: null, isLoading: true }));

        void readDrafts({ signal: abortController.signal })
            .then((page) => {
                if (listReadGenerationRef.current !== generation) return;
                setListState({
                    error: null,
                    isLoading: false,
                    nextCursor: getNextCursor(page),
                    rows: page.items,
                });
                setSelection((currentSelection) => {
                    if (currentSelection !== null || routeSelectionKey.length > 0)
                        return currentSelection;
                    const nextSelection =
                        page.items.length === 0 ? null : draftIdentityFromSummary(page.items[0]);
                    selectedIdentityKeyRef.current =
                        nextSelection === null ? "" : draftIdentityKey(nextSelection);
                    return nextSelection;
                });
            })
            .catch((error: unknown) => {
                if (isApiAbortError(error) || listReadGenerationRef.current !== generation) return;
                setListState((currentState) => ({
                    ...currentState,
                    error: toErrorView(error),
                    isLoading: false,
                }));
            });
        return () => abortController.abort();
    }, [refreshToken, routeSelectionKey]);

    useEffect(() => {
        if (selection === null) {
            setDetailState(initialDetailState);
            setEditorBody("");
            setDraftActionDialog(null);
            setDraftConfirmation(null);
            setOperationError(null);
            return;
        }

        const abortController = new AbortController();
        const generation = detailReadGenerationRef.current + 1;
        detailReadGenerationRef.current = generation;
        const identityKey = draftIdentityKey(selection);
        setDetailState({ draft: null, error: null, isLoading: true });
        setDraftActionDialog(null);
        setDraftConfirmation(null);
        setOperationError(null);

        void readDraft({ ...selection, signal: abortController.signal })
            .then((response) => {
                if (!isCurrentDetailRead(generation, identityKey, response.draft)) return;
                applyDraftDetail(response.draft, { includeInList: response.draft.is_saved });
            })
            .catch((error: unknown) => {
                if (
                    isApiAbortError(error) ||
                    detailReadGenerationRef.current !== generation ||
                    selectedIdentityKeyRef.current !== identityKey
                ) {
                    return;
                }
                setDetailState({ draft: null, error: toErrorView(error), isLoading: false });
                setEditorBody("");
            });
        return () => abortController.abort();
    }, [applyDraftDetail, detailRefreshToken, selectedKey, selection]);

    useEffect(() => {
        if (navigationBlocker.state === "blocked" && !isBusy && !isDirty) {
            navigationBypassRef.current = true;
            navigationBlocker.proceed();
            queueMicrotask(() => {
                navigationBypassRef.current = false;
            });
        }
    }, [isBusy, isDirty, navigationBlocker]);

    function isCurrentDetailRead(
        generation: number,
        identityKey: string,
        draft: DraftDetail,
    ): boolean {
        return (
            detailReadGenerationRef.current === generation &&
            selectedIdentityKeyRef.current === identityKey &&
            draftIdentityKey(draft) === identityKey
        );
    }

    const applyDraftSelection = useCallback(
        (identity: DraftIdentity | null, discardLocalEdits = false) => {
            if (discardLocalEdits) navigationBypassRef.current = true;
            if (!isDirty || discardLocalEdits) {
                selectedIdentityKeyRef.current =
                    identity === null ? "" : draftIdentityKey(identity);
                setSelection(identity);
            }
            setSearchParams(identity === null ? {} : { key: identity.key, kind: identity.kind });
            if (discardLocalEdits) {
                queueMicrotask(() => {
                    navigationBypassRef.current = false;
                });
            }
        },
        [isDirty, setSearchParams],
    );

    function beginOperation(
        nextOperation: Exclude<DraftOperation, null>,
    ): DraftOperationContext | null {
        if (currentDraft === null) return null;
        const context = {
            generation: operationGenerationRef.current + 1,
            identityKey: draftIdentityKey(currentDraft),
        };
        operationGenerationRef.current = context.generation;
        setOperation(nextOperation);
        setOperationError(null);
        return context;
    }

    function isCurrentOperation(context: DraftOperationContext): boolean {
        return (
            operationGenerationRef.current === context.generation &&
            selectedIdentityKeyRef.current === context.identityKey
        );
    }

    async function persistCurrentDraftIfNeeded(
        context: DraftOperationContext,
    ): Promise<DraftDetail | null> {
        if (currentDraft === null || draftIdentityKey(currentDraft) !== context.identityKey)
            return null;
        if (currentDraft.is_saved && !isDirty) return currentDraft;
        const response = await saveDraftRequest({
            body: editorBody,
            key: currentDraft.key,
            kind: currentDraft.kind,
        });
        if (
            !isCurrentOperation(context) ||
            draftIdentityKey(response.draft) !== context.identityKey
        ) {
            return null;
        }
        applyDraftDetail(response.draft);
        return response.draft;
    }

    async function handleSaveDraft(): Promise<void> {
        const context = beginOperation("saving");
        if (context === null || currentDraft === null) return;
        try {
            const response = await saveDraftRequest({
                body: editorBody,
                key: currentDraft.key,
                kind: currentDraft.kind,
            });
            if (
                isCurrentOperation(context) &&
                draftIdentityKey(response.draft) === context.identityKey
            ) {
                applyDraftDetail(response.draft);
            }
        } catch (error) {
            if (isCurrentOperation(context)) setOperationError(toErrorView(error));
        } finally {
            if (operationGenerationRef.current === context.generation) setOperation(null);
        }
    }

    async function handleValidateDraft(): Promise<void> {
        const context = beginOperation("validating");
        if (context === null) return;
        try {
            const savedDraft = await persistCurrentDraftIfNeeded(context);
            if (savedDraft === null) return;
            const response = await validateDraftRequest({
                key: savedDraft.key,
                kind: savedDraft.kind,
            });
            if (isCurrentOperation(context) && draftIdentityKey(response) === context.identityKey) {
                setDraftActionDialog({ kind: "validation", validation: response });
            }
        } catch (error) {
            if (isCurrentOperation(context)) {
                setOperationError(toErrorView(error));
                setDraftActionDialog(null);
            }
        } finally {
            if (operationGenerationRef.current === context.generation) setOperation(null);
        }
    }

    async function handlePublishDraft(): Promise<void> {
        const context = beginOperation("publishing");
        if (context === null) return;
        try {
            const savedDraft = await persistCurrentDraftIfNeeded(context);
            if (savedDraft === null) return;
            const response = await publishDraftRequest({
                key: savedDraft.key,
                kind: savedDraft.kind,
            });
            if (!isCurrentOperation(context) || draftIdentityKey(response) !== context.identityKey)
                return;
            setDraftActionDialog({ kind: "publish", result: response });
            if (response.status === "published") {
                removeListSummary(savedDraft);
                const currentResponse = await readDraft({
                    key: savedDraft.key,
                    kind: savedDraft.kind,
                });
                if (
                    !isCurrentOperation(context) ||
                    draftIdentityKey(currentResponse.draft) !== context.identityKey
                ) {
                    return;
                }
                applyDraftDetail(currentResponse.draft, {
                    clearOutcome: false,
                    includeInList: currentResponse.draft.is_saved,
                });
                setDraftActionDialog({ kind: "publish", result: response });
            }
        } catch (error) {
            if (isCurrentOperation(context)) {
                setOperationError(toErrorView(error));
                setDraftActionDialog(null);
            }
        } finally {
            if (operationGenerationRef.current === context.generation) setOperation(null);
        }
    }

    async function handleCreateDraft(): Promise<void> {
        const key = normalizeDraftKey(newDraftForm.key);
        if (key.length === 0) {
            setNewDraftForm((form) => ({ ...form, error: formError("Draft key is required.") }));
            return;
        }
        const generation = createGenerationRef.current + 1;
        createGenerationRef.current = generation;
        const identity = { key, kind: newDraftForm.kind };
        setNewDraftForm((form) => ({ ...form, error: null, isCreating: true }));
        try {
            const response = await createDraft({
                body:
                    newDraftForm.mode === "create"
                        ? starterBodyForKind(newDraftForm.kind, key, newDraftForm.description)
                        : undefined,
                key,
                kind: newDraftForm.kind,
                mode: newDraftForm.mode,
            });
            if (
                createGenerationRef.current !== generation ||
                draftIdentityKey(response.draft) !== draftIdentityKey(identity)
            ) {
                return;
            }
            applyDraftDetail(response.draft);
            setNewDraftForm(initialNewDraftForm);
            applyDraftSelection(identity);
        } catch (error) {
            if (createGenerationRef.current === generation) {
                setNewDraftForm((form) => ({
                    ...form,
                    error: toErrorView(error),
                    isCreating: false,
                }));
            }
        }
    }

    function removeListSummary(identity: DraftIdentity): void {
        setListState((state) => ({
            ...state,
            rows: state.rows.filter(
                (row) => !draftIdentityEquals(draftIdentityFromSummary(row), identity),
            ),
        }));
    }

    async function runConfirmedDraftAction(action: DraftConfirmation): Promise<void> {
        const nextOperation =
            action === "discard" ? "discarding" : action === "replace" ? "replacing" : "resetting";
        const context = beginOperation(nextOperation);
        if (context === null || currentDraft === null) return;
        try {
            if (action === "discard") {
                await discardDraft(context, currentDraft);
            } else if (action === "replace") {
                await replaceDraft(context, currentDraft);
            } else {
                await resetDraft(context, currentDraft);
            }
        } catch (error) {
            if (isCurrentOperation(context)) setOperationError(toErrorView(error));
        } finally {
            if (operationGenerationRef.current === context.generation) setOperation(null);
        }
    }

    async function discardDraft(context: DraftOperationContext, draft: DraftDetail): Promise<void> {
        if (!draft.is_saved) return;
        const identity = { key: draft.key, kind: draft.kind };
        const remainingRows = listState.rows.filter(
            (row) => !draftIdentityEquals(draftIdentityFromSummary(row), identity),
        );
        await deleteDraft(identity);
        if (!isCurrentOperation(context)) return;
        setDraftConfirmation(null);
        removeListSummary(identity);
        if (draft.mode === "update") {
            const response = await readDraft(identity);
            if (
                isCurrentOperation(context) &&
                draftIdentityKey(response.draft) === context.identityKey
            ) {
                applyDraftDetail(response.draft, { includeInList: response.draft.is_saved });
            }
            return;
        }
        const nextSelection =
            remainingRows.length === 0 ? null : draftIdentityFromSummary(remainingRows[0]);
        applyDraftSelection(nextSelection, true);
    }

    async function replaceDraft(context: DraftOperationContext, draft: DraftDetail): Promise<void> {
        if (draft.mode !== "update" || !draft.is_saved) return;
        const response = await replaceDraftWithCurrent({ key: draft.key, kind: draft.kind });
        if (
            isCurrentOperation(context) &&
            draftIdentityKey(response.draft) === context.identityKey
        ) {
            applyDraftDetail(response.draft);
            setDraftConfirmation(null);
        }
    }

    async function resetDraft(context: DraftOperationContext, draft: DraftDetail): Promise<void> {
        const baselineBody = draft.baseline_body;
        if (!draft.is_saved || baselineBody === null || baselineBody === undefined) return;
        const response = await saveDraftRequest({
            body: baselineBody,
            key: draft.key,
            kind: draft.kind,
        });
        if (
            isCurrentOperation(context) &&
            draftIdentityKey(response.draft) === context.identityKey
        ) {
            applyDraftDetail(response.draft);
            setDraftConfirmation(null);
        }
    }

    function handleDraftBodyKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
        if (event.key !== "Tab") return;
        event.preventDefault();
        const target = event.currentTarget;
        const edit = applyDraftBodyIndentation({
            body: editorBody,
            selectionEnd: target.selectionEnd,
            selectionStart: target.selectionStart,
            shouldOutdent: event.shiftKey,
        });
        setEditorBody(edit.body);
        window.requestAnimationFrame(() =>
            target.setSelectionRange(edit.selectionStart, edit.selectionEnd),
        );
    }

    function keepBlockedNavigation(): void {
        if (navigationBlocker.state === "blocked") navigationBlocker.reset();
        setIsNewDraftBlocked(false);
    }

    function discardBlockedNavigation(): void {
        if (currentDraft !== null) setEditorBody(currentDraft.body);
        if (navigationBlocker.state === "blocked") {
            navigationBlocker.proceed();
            return;
        }
        setIsNewDraftBlocked(false);
        setNewDraftForm({ ...initialNewDraftForm, isOpen: true });
    }

    return {
        cancelDraftConfirmation: () => {
            if (!isBusy) {
                setDraftConfirmation(null);
                setOperationError(null);
            }
        },
        closeDraftActionDialog: () => setDraftActionDialog(null),
        closeNewDraftDialog: () => {
            if (!newDraftForm.isCreating) setNewDraftForm(initialNewDraftForm);
        },
        confirmDraftAction: () => {
            if (draftConfirmation !== null) void runConfirmedDraftAction(draftConfirmation);
        },
        createNewDraft: () => void handleCreateDraft(),
        currentDraft,
        detailState,
        discardBlockedNavigation,
        draftActionDialog,
        draftConfirmation,
        editorBody,
        handleDraftBodyKeyDown,
        isBusy,
        isDirty,
        isNewDraftBlocked,
        isOperationNavigationBlocked: navigationBlocker.state === "blocked" && isBusy,
        isUnsavedNavigationBlocked:
            isNewDraftBlocked || (navigationBlocker.state === "blocked" && !isBusy),
        keepBlockedNavigation,
        listState,
        loadMoreDrafts: () => {
            if (listState.nextCursor === null || listState.isLoading) return;
            const cursor = listState.nextCursor;
            setListState((state) => ({ ...state, isLoading: true }));
            void readDrafts({ cursor })
                .then((page) => {
                    setListState((state) => ({
                        error: null,
                        isLoading: false,
                        nextCursor: getNextCursor(page),
                        rows: [...state.rows, ...page.items],
                    }));
                })
                .catch((error: unknown) => {
                    if (!isApiAbortError(error)) {
                        setListState((state) => ({
                            ...state,
                            error: toErrorView(error),
                            isLoading: false,
                        }));
                    }
                });
        },
        newDraftForm,
        openDraftConfirmation: (action) => {
            setDraftActionDialog(null);
            setOperationError(null);
            setDraftConfirmation(action);
        },
        openNewDraftDialog: () => {
            if (isDirty) {
                setIsNewDraftBlocked(true);
                return;
            }
            setNewDraftForm({ ...initialNewDraftForm, isOpen: true });
        },
        operation,
        operationError,
        publishDraft: () => void handlePublishDraft(),
        refreshList: () => setRefreshToken((value) => value + 1),
        refreshSelected: () => setDetailRefreshToken((value) => value + 1),
        saveDraft: () => void handleSaveDraft(),
        selectDraft: (identity) => {
            if (!draftIdentityEquals(identity, selection)) applyDraftSelection(identity);
        },
        selection,
        setEditorBody,
        setNewDraftForm,
        validateDraft: () => void handleValidateDraft(),
    };
}
