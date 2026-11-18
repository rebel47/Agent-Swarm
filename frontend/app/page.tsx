"use client";
import {useEffect, useState} from "react";
import {api} from "../lib/api";
import {draftFromReview, startReview, type PreparationStage, type ReviewDraft, type ReviewInput} from "../lib/reviews";
import {useWorkspace} from "../hooks/use-workspace";
import {useReview, useReviewSelection} from "../hooks/use-review";
import {WorkspaceShell} from "../components/workspace-shell";
import {ConnectWorkspace} from "../components/connect-workspace";
import {NewReview} from "../components/new-review";
import {ReviewView} from "../components/review-view";
import {WorkspaceSettings} from "../components/workspace-settings";
import {Brand, Icon} from "../components/ui";

export default function Home() {
  const [error, setError] = useState(""), [settingsOpen, setSettingsOpen] = useState(false);
  const [stage, setStage] = useState<PreparationStage>("");
  const [draft, setDraft] = useState<ReviewDraft>();
  const [draftKey, setDraftKey] = useState(0);
  const workspace = useWorkspace(setError);
  const selection = useReviewSelection();
  const review = useReview(selection.id, workspace.connected ? workspace.token : "", setError);
  const {refreshHistory} = workspace;
  useEffect(() => {
    if (workspace.connected) void refreshHistory().catch(error => setError(String(error)));
  }, [workspace.connected, review.job?.status, refreshHistory]);
  function newReview() {if (stage) return; setDraft(undefined); setDraftKey(key => key + 1); selection.select(""); setError("");}
  async function start(input: ReviewInput) {
    if (stage) return;
    setStage("Starting review"); setError("");
    try {
      const created = await startReview(workspace.token, input, workspace.allocation, setStage);
      selection.select(created.id);
      await Promise.all([workspace.refreshSources(), workspace.refreshHistory()]).catch(() => {
        setError("Your review has started. The workspace list could not refresh; reopen it to try again.");
      });
    } catch (error) {setError(String(error));} finally {setStage("");}
  }
  async function remove(id: string) {
    try {await api("/repositories/" + id, workspace.token, {method: "DELETE"}); await workspace.refreshSources(); return true;}
    catch (error) {setError(String(error)); return false;}
  }
  async function cancel() {
    try {await api("/jobs/" + selection.id + "/cancel", workspace.token, {method: "POST"}); await review.refresh();}
    catch (error) {setError(String(error));}
  }
  return <>
    {workspace.loading && !workspace.connected ? <div className="initial-loading"><Brand /><span className="spinner" />
      <p>Opening your workspace...</p></div> : !workspace.connected ?
      <ConnectWorkspace connect={workspace.connect} loading={workspace.loading} /> :
      <WorkspaceShell history={workspace.history} currentId={selection.id} select={id => {selection.select(id); setError("");}}
        newReview={newReview} settings={() => setSettingsOpen(true)} connected={workspace.connected}
        disconnect={() => {workspace.disconnect(); selection.select("");}}>
        {!selection.id ? <NewReview key={draftKey} sources={workspace.sources} stage={stage} start={start} remove={remove} initial={draft} /> :
          review.job ? <ReviewView key={review.job.id} job={review.job} audit={review.audit} token={workspace.token}
            now={review.now} connection={review.connection} onError={setError} cancel={cancel} again={() => {
              if (review.job) setDraft(draftFromReview(review.job));
              setDraftKey(key => key + 1); selection.select("");
            }} /> : <div className="review-loading" role="status"><span className="spinner" />Opening review...</div>}
      </WorkspaceShell>}
    {settingsOpen && workspace.connected && <WorkspaceSettings models={workspace.models} allocation={workspace.allocation}
      change={workspace.setAllocation} token={workspace.token} close={() => setSettingsOpen(false)} />}
    {error && <div className="error-toast" role="alert"><Icon name="alert" /><p>{error.replace(/^Error: /, "")}</p>
      <button className="icon-button" aria-label="Dismiss error" onClick={() => setError("")}><Icon name="close" size={16} /></button></div>}
  </>;
}
