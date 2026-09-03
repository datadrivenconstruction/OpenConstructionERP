// Ported verbatim from the approved interactive preview (Sep 2026).
// This template is static and trusted - every piece of server data
// is rendered into it by the engine through its own esc() helper.
export const STANDUP_MARKUP = `
<div class="wrap">

  <div class="app">

    <div class="page-head">
      <div class="page-title">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        <div>
          <h2>Team Standup</h2>
          <p class="date" id="dateLine">Tuesday, 1 September 2026</p>
        </div>
      </div>
      <div class="head-controls">
        <span class="daynav">
          <button class="step" id="dayPrev" title="Previous day">&lsaquo;</button>
          <input class="datebox" id="dayPick" type="date">
          <button class="step" id="dayNext" title="Next day">&rsaquo;</button>
        </span>
        <button class="icon-btn" id="dayToday">Today</button>
        <button class="icon-btn sq" id="tilesToggle" title="Open or close every tile"></button>
      </div>
    </div>

    <!-- ===== MY UPDATE ===== -->
    <section class="tile" id="tile-me" open-state="1" style="--tint:var(--c-blue);--tint-wash:var(--w-blue);">
      <header class="tile-head" data-toggle data-menu="tile" data-label="Tile">
        <span class="tw">&#9660;</span>
        <h3>My update</h3>
        <span class="meta" id="meMeta"></span>
        <span class="spacer"></span>
        <span class="tile-tools">
          <button class="icon-btn" id="sameAsYesterday" title="Copy yesterday's plan into today">Same as yesterday</button>
          <button class="icon-btn" data-settings="me">Customise</button>
        </span>
      </header>
      <div class="tile-body">

        <div class="settings" id="set-me">
          <h4>Where people can say they are</h4>
          <p class="why">Type to rename. Click a colour. Drag a row by its handle to reorder, or use the arrows. <b>Exclusive</b> means picking it clears the others.</p>
          <div id="actCfg" style="display:flex;flex-direction:column;gap:8px;"></div>
          <div class="cfg-foot">
            <button class="btn btn-quiet" id="addAct">+ Add activity</button>
            <span class="lbl-sm">Saved per workspace, editable any time.</span>
          </div>
        </div>

        <div id="nudge"></div>

        <div>
          <span class="field-label">Where I am today <span class="hint">&mdash; pick as many as apply</span></span>
          <div class="chipset" id="statusChips"></div>
        </div>

        <div>
          <span class="field-label">Jobs I am on today</span>
          <div class="picker-head">
            <input type="text" id="jobSearch" placeholder="Search by number, client or work...">
            <span class="scrollnote" id="jobPickMeta"></span>
            <span style="margin-left:auto"></span>
            <button class="icon-btn" id="showPicked" aria-pressed="false">Only mine</button>
          </div>
          <div class="chiprow tight" id="clientChips" style="margin-bottom:7px"></div>
          <div class="tablewrap h-jobs">
            <table id="jobTable">
              <thead><tr>
                <th style="width:36px"></th><th>Job</th><th>Client</th><th>Work</th><th class="tkh">My tasks</th>
              </tr></thead>
              <tbody id="jobBody"></tbody>
            </table>
          </div>
        </div>

        <div class="grid3">
          <label>
            <span class="field-label">Yesterday</span>
            <textarea id="fYest" rows="3"></textarea>
          </label>
          <label>
            <span class="field-label">Today</span>
            <textarea id="fToday" rows="3"></textarea>
          </label>
          <div>
            <span class="field-label warn" data-menu="field" data-field="blocker">Blocker</span>
            <textarea id="fBlock" rows="3"></textarea>
            <label style="display:flex;align-items:center;gap:7px;margin-top:6px;">
              <span class="hint" style="white-space:nowrap">Need it by</span>
              <input type="date" id="fBlockBy" style="font-family:'IBM Plex Mono',monospace;font-size:12px;padding:5px 7px;">
            </label>
          </div>
        </div>

        <div>
          <span class="field-label">Add tasks <span class="hint">&mdash; they land on the job's list too</span></span>
          <div class="addrows" id="addRows"></div>
          <div class="addfoot">
            <span class="hint" id="addHint"></span>
            <span style="margin-left:auto"></span>
            <button type="button" class="btn btn-quiet" id="addClear">Clear all</button>
            <button type="button" class="btn btn-quiet" id="addLine">+ Add new line</button>
          </div>
          <div id="addedReceipts"></div>
        </div>

        <div>
          <span class="field-label">Attachments <span class="hint">&mdash; photos, dockets, drawings, anything worth showing</span></span>
          <div class="photos" id="myPhotos"></div>
          <input type="file" id="photoInput" multiple style="display:none">
        </div>

        <div class="mine-foot">
          <span class="hint" id="saveHint"></span>
          <button class="btn btn-primary" id="saveBtn">Save my update</button>
        </div>
      </div>
    </section>

    <!-- ===== THE TEAM ===== -->
    <section class="tile" id="tile-team" open-state="1" style="--tint:var(--c-violet);--tint-wash:var(--w-violet);">
      <header class="tile-head" data-toggle data-menu="tile" data-label="Tile">
        <span class="tw">&#9660;</span>
        <h3>The team</h3>
        <span class="meta" id="teamMeta"></span>
        <span class="spacer"></span>
        <span class="tile-tools">
          <button class="icon-btn" id="viewToday" aria-pressed="true">Today</button>
          <button class="icon-btn" id="viewWeek" aria-pressed="false">Week</button>
          <button class="icon-btn" id="viewCap" aria-pressed="false">Capacity</button>
          <button class="icon-btn sq" id="teamToggle" title="Expand or collapse every card"></button>
          <button class="icon-btn" id="digestBtn">Weekly digest</button>
        </span>
      </header>
      <div class="tile-body">
        <div class="board" id="teamBoard"></div>
        <div class="caps" id="capWrap" style="display:none;"></div>
        <p class="note" id="capNote" style="display:none;"><b>Who is carrying what.</b> The bar splits each person's open work into overdue, waiting and running. Click a row to filter the board to them.</p>
        <div class="tablewrap h-week" id="weekWrap" style="display:none;">
          <table id="weekTable"><thead><tr id="weekHead"></tr></thead><tbody id="weekBody"></tbody></table>
        </div>
        <p class="note" id="weekNote" style="display:none;"><b>Two dots is a mixed day.</b> The time under each entry is when it was posted. <b>!</b> flags a blocker.</p>
      </div>
    </section>

    <!-- ===== BLOCKERS ===== -->
    <section class="tile" id="tile-blockers" open-state="1" style="--tint:var(--c-amber);--tint-wash:var(--w-amber);">
      <header class="tile-head" data-toggle data-menu="tile" data-label="Tile">
        <span class="tw">&#9660;</span>
        <h3>What's holding us up</h3>
        <span class="meta" id="blkMeta"></span>
        <span class="spacer"></span>
      </header>
      <div class="tile-body">
        <ul class="blk-list" id="blkList"></ul>
        <p class="note">One list, two sources: blockers typed into a standup, and any task flagged <b>waiting</b>. Sorted by the date it is needed &mdash; red is past due.</p>
      </div>
    </section>

    <!-- ===== TASKS ===== -->
    <section class="tile" id="tile-tasks" open-state="1" style="--tint:var(--c-teal);--tint-wash:var(--w-teal);">
      <header class="tile-head" data-toggle data-menu="tile" data-label="Tile">
        <span class="tw">&#9660;</span>
        <h3>Tasks &amp; delivery board</h3>
        <span class="meta" id="taskMeta"></span>
        <span class="spacer"></span>
        <span class="tile-tools">
          <button class="icon-btn" data-settings="stages">Customise stages</button>
        </span>
      </header>
      <div class="tile-body">

        <div class="settings" id="set-stages">
          <h4>Delivery stages</h4>
          <p class="why">Type to rename. Click a colour dot. Drag by the handle or use the arrows to reorder. <b>WIP</b> warns when a stage is overloaded. <b>Closes the task</b> marks the finished stages. On the board itself: double-click a column name to rename it, click its dot to recolour, drag a column header to reorder, or open its &#8942; menu.</p>
          <div class="stagescope">
            <span class="lbl">Applies to</span>
            <div class="chiprow tight" id="stageScope"></div>
            <span class="scopehint" id="stageScopeHint"></span>
          </div>
          <p class="why" id="stageScopeNote" hidden></p>
          <div id="stageCfg" style="display:flex;flex-direction:column;gap:8px;"></div>
          <div class="cfg-foot">
            <button class="btn btn-quiet" id="addStage">+ Add stage</button>
            <button class="btn btn-quiet" id="resetStages">Reset to the electrical run</button>
            <button class="btn btn-quiet" id="startOwnStages" hidden>Start from the standard stages</button>
            <button class="btn btn-quiet" id="removeOwnStages" hidden>Remove this job's own stages</button>
          </div>
        </div>

        <div class="toolbar" data-menu="toolbar" data-label="Filters">
          <div class="subtabs" role="tablist">
            <button role="tab" aria-selected="true" data-sub="list">List</button>
            <button role="tab" aria-selected="false" data-sub="board">Board</button>
            <button role="tab" aria-selected="false" data-sub="month">Month</button>
          </div>
          <input class="filterbox" id="taskFilter" type="text" placeholder="Filter tasks..." style="width:180px">
          <select class="filterbox" id="jobFilter" style="width:180px"><option value="">All jobs</option></select>
          <select class="filterbox" id="clientFilter" style="width:150px"><option value="">All clients</option></select>
          <button type="button" class="filterbox fbtn" id="whoFilter" title="Filter by person - pick as many as you like">Everyone</button>
          <button class="icon-btn" id="waitOnly" aria-pressed="false">Waiting only</button>
          <button class="icon-btn" id="dueOnly" aria-pressed="false">Overdue only</button>
          <span class="sizer" title="Text size and row height">
            <button type="button" id="szDown">&minus;</button>
            <span class="val" id="szVal"></span>
            <button type="button" id="szUp">+</button>
            <button type="button" id="szReset" title="Reset the table" style="width:auto;padding:0 8px;font-size:11px">reset</button>
          </span>
          <div class="avatars" id="avatarStack"></div>
        </div>
        <div class="toolbar filters2" data-menu="toolbar" data-label="Filters">
          <span class="lbl-sm">Deliverable</span>
          <div class="chiprow tight" id="delivKinds" style="margin-top:0"></div>
          <button type="button" class="filterbox fbtn" id="recordFilter" title="Only the tasks linked to one particular record">Specific deliverable&hellip;</button>
          <span class="fsep"></span>
          <button type="button" class="filterbox fbtn" id="stageFilter">Any stage</button>
          <button type="button" class="filterbox fbtn" id="prioFilter">Any priority</button>
          <button type="button" class="filterbox fbtn" id="dueFilter">Due: any</button>
          <span class="daterange" id="dueRange" hidden><input type="date" id="dueFrom" title="From"><span>to</span><input type="date" id="dueTo" title="To"></span>
          <button type="button" class="filterbox fbtn" id="visFilter">All tasks</button>
          <span style="margin-left:auto"></span>
          <button type="button" class="filterbox fbtn" id="groupBy" title="Group the list into sections">Group: none</button>
        </div>
        <div class="activefilters" id="activeFilters"></div>

        <div id="view-list" class="tablewrap h-tasks">
          <table id="listTable">
            <thead><tr id="listHead"></tr></thead>
            <tbody id="listBody"></tbody>
            <tfoot><tr class="createrow"><td colspan="12"><button class="createbtn" id="createBtn">+ Create task</button></td></tr></tfoot>
          </table>
        </div>

        <div id="view-board" style="display:none;">
          <div class="boardscope" id="boardScope" hidden></div>
          <div class="kanban" id="kanban"></div>
        </div>

        <div id="view-month" style="display:none;">
          <div class="monthhead">
            <button class="step" id="monthPrev" title="Previous month">&lsaquo;</button>
            <h4 id="monthLabel"></h4>
            <button class="step" id="monthNext" title="Next month">&rsaquo;</button>
            <button class="icon-btn" id="monthToday">This month</button>
            <span class="mlegend">
              <span><i class="solid"></i> a real task</span>
              <span><i class="dash"></i> a repeat still to come</span>
            </span>
          </div>
          <div class="mtray" id="monthTray" hidden>
            <div class="mtray-head" data-menu="tray" data-label="No date yet">
              <span class="lbl">No date yet</span>
              <span class="cnt" id="monthTrayCount"></span>
              <span class="hint">drag a task onto a day to give it a due date</span>
            </div>
            <div class="mtray-body" id="monthTrayBody"></div>
          </div>
          <div class="monthgrid" id="monthGrid"></div>
          <p class="note"><b>Repeats are shown, not created.</b> Only the current occurrence is a real task; the dashed ones are what the rule will produce when each is closed out. That keeps the list honest and stops a missed weekly task piling up six copies.</p>
        </div>

      </div>
    </section>

    <!-- ===== ACTIVITY LOG ===== -->
    <section class="tile" id="tile-log" open-state="0" style="--tint:var(--c-slate);--tint-wash:var(--w-slate);">
      <header class="tile-head" data-toggle data-menu="tile" data-label="Tile">
        <span class="tw">&#9660;</span>
        <h3>Activity log</h3>
        <span class="meta" id="logMeta"></span>
        <span class="spacer"></span>
        <span class="tile-tools">
          <select class="filterbox" id="logFilter" style="width:150px">
            <option value="">Everything</option>
            <option value="task">Tasks</option>
            <option value="standup">Standups</option>
            <option value="config">Settings</option>
          </select>
        </span>
      </header>
      <div class="tile-body">
        <div class="tablewrap h-log">
          <table id="logTable">
            <thead><tr><th style="width:74px">Time</th><th style="width:120px">Who</th><th>What changed</th><th style="width:110px">Where</th></tr></thead>
            <tbody id="logBody"></tbody>
          </table>
        </div>
      </div>
    </section>
  </div>

</div>

<!-- edit task modal -->
<div class="scrim" id="scrim">
 <div class="pairwrap" id="pairWrap">
  <div class="modal" role="dialog" aria-modal="true" id="mModal">
    <div class="modal-head" id="mHead">
      <span class="mstage" id="mHeadStage"></span>
      <span class="mstage mvis" id="mHeadVis" hidden title="Private - only you and the assignee see it">&#128274; Private</span>
      <h3 id="mTitle">Edit task</h3>
      <span class="mref" id="mHeadRef"></span>
      <button class="x" id="mClose">&#10005;</button>
    </div>
    <div class="modal-body">

      <div class="fgroup">
        <span class="field-label">What needs doing</span>
        <div class="combo"><input type="text" id="mSummary" placeholder="Start typing..." autocomplete="off"><button type="button" class="combo-btn" data-for="mSummary">&#9662;</button></div>
      </div>

      <div class="fgroup">
        <span class="field-label">Job</span>
        <div class="combo"><input type="text" id="mJob" placeholder="Search jobs..." autocomplete="off"><button type="button" class="combo-btn" data-for="mJob">&#9662;</button></div>
      </div>

      <div class="modal-grid">
        <div class="fgroup">
          <span class="field-label">Stage in the run</span>
          <button type="button" class="pickbtn" id="mStageBtn"></button>
        </div>
        <div class="fgroup">
          <span class="field-label">Assignee</span>
          <button type="button" class="pickbtn" id="mWhoBtn"></button>
        </div>
        <div class="fgroup">
          <span class="field-label">Priority</span>
          <button type="button" class="pickbtn" id="mPrioBtn"></button>
        </div>
        <div class="fgroup">
          <span class="field-label">Repeats</span>
          <button type="button" class="pickbtn" id="mRepBtn"></button>
        </div>
      </div>
      <span class="spawnnote" id="mSpawn"></span>

      <div class="fgroup">
        <span class="field-label">Who can see it</span>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <div class="segctl" id="mVis" role="radiogroup" aria-label="Visibility">
            <button type="button" data-vis="public" aria-pressed="true">Public</button>
            <button type="button" data-vis="private" aria-pressed="false">&#128274; Private</button>
          </div>
          <span class="hint" id="mVisNote"></span>
        </div>
      </div>

      <div class="fgroup">
        <span class="field-label warn">Waiting on <span class="hint">&mdash; pick one or type your own</span></span>
        <div class="combo"><input type="text" id="mWait" placeholder="Nothing is holding it up" autocomplete="off"><button type="button" class="combo-btn" data-for="mWait">&#9662;</button></div>
      </div>

      <div class="fgroup">
        <span class="field-label">Due date</span>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <input type="date" id="mDue" style="width:160px">
          <div class="chiprow tight" id="mDueQuick"></div>
        </div>
        <span class="spawnnote" id="mRepNote"></span>
      </div>

      <div class="fgroup">
        <span class="field-label">Linked record <span class="hint">&mdash; the RFI, order or email this came off</span></span>
        <div style="display:flex;gap:8px;align-items:center">
          <button type="button" class="pickbtn" id="mLinkBtn" style="flex:1 1 auto"></button>
          <button class="icon-btn" type="button" id="mLinkOpen" title="Show it beside this task">Open it &#9656;</button>
        </div>
        <input type="hidden" id="mLinkRef">
      </div>

      <div class="fgroup">
        <span class="field-label">Notes</span>
        <textarea id="mNotes" rows="3" placeholder="Anything the next person needs to know"></textarea>
      </div>

      <div class="fgroup">
        <span class="field-label">Attachments <span class="hint">&mdash; drawings, photos, video, dockets</span></span>
        <div class="filelist" id="mFiles"></div>
        <div class="dropzone" id="mDrop">Drop files here, or click to choose</div>
        <input type="file" id="mFileInput" multiple style="display:none">
      </div>

      <div class="fgroup" id="mCommentsWrap">
        <span class="field-label">Comments <span class="hint" id="mCommentCount"></span></span>
        <div class="tcomments" id="mComments"></div>
        <form class="reply-row" id="mCommentForm">
          <input type="text" id="mCommentBox" placeholder="Add a comment... type @ to mention">
          <button class="send" type="submit" title="Post">&rarr;</button>
        </form>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-danger" id="mDelete">Delete</button>
      <span class="spacer"></span>
      <button class="btn btn-quiet" id="mCancel">Cancel</button>
      <button class="btn btn-primary" id="mSave">Save task</button>
    </div>
  </div>

  <aside class="recpanel" id="recPanel" aria-live="polite">
    <div class="recpanel-inner">
      <div class="modal-head">
        <span class="mstage" id="recTag"></span>
        <h3 id="recTitle"></h3>
        <button class="x" id="recClose">&#10005;</button>
      </div>
      <div class="modal-body" id="recBody"></div>
      <div class="modal-foot">
        <span class="spacer"></span>
        <button class="btn btn-quiet" id="recOpenModule">Open in the module</button>
      </div>
    </div>
  </aside>
 </div>
</div>

<div class="scrim" id="pickScrim">
  <div class="modal" role="dialog" aria-modal="true" style="max-width:min(1240px,96vw)">
    <div class="modal-head">
      <h3 id="pickTitle">Link to an existing record</h3>
      <span class="mref" id="pickFor"></span>
      <button class="x" id="pickClose">&#10005;</button>
    </div>
    <div class="pickbar">
      <div class="combo" style="flex:0 0 240px"><input type="text" id="pickSearch" placeholder="Search reference, title or party..." autocomplete="off"></div>
      <div class="chiprow" id="pickKinds"></div>
      <button class="icon-btn" id="pickScope" aria-pressed="true">This job only</button>
    </div>
    <div class="pickbody">
      <div class="picklist" id="pickList"></div>
      <div class="pickview" id="pickView"></div>
    </div>
    <div class="modal-foot">
      <span class="lbl-sm" id="pickCount"></span>
      <span class="spacer"></span>
      <button class="btn btn-quiet" id="pickCancel">Cancel</button>
      <button class="btn btn-primary" id="pickConfirm">Link this record</button>
    </div>
  </div>
</div>

<div class="scrim" id="newRecScrim">
  <div class="modal" role="dialog" aria-modal="true" style="max-width:560px">
    <div class="modal-head"><h3>Raise a new record</h3><button class="x" id="newRecClose">&#10005;</button></div>
    <div class="modal-body">
      <div class="fgroup">
        <span class="field-label">What are you raising?</span>
        <div class="chiprow" id="newRecKinds"></div>
      </div>
      <div class="fgroup">
        <span class="field-label">Title</span>
        <input type="text" id="newRecTitle" placeholder="What is it about?">
      </div>
      <div class="fgroup">
        <span class="field-label">Job</span>
        <input type="text" id="newRecJob" readonly style="font-family:'IBM Plex Mono',monospace">
      </div>
      <div class="fgroup">
        <span class="field-label">It will be created as</span>
        <span class="spawnnote" id="newRecPreview"></span>
      </div>
    </div>
    <div class="modal-foot">
      <span class="spacer"></span>
      <button class="btn btn-quiet" id="newRecCancel">Cancel</button>
      <button class="btn btn-primary" id="newRecSave">Raise and link</button>
    </div>
  </div>
</div>

<div class="scrim" id="infoScrim">
  <div class="modal" role="dialog" aria-modal="true" style="max-width:620px">
    <div class="modal-head"><h3 id="infoTitle"></h3><button class="x" id="infoClose">&#10005;</button></div>
    <div class="modal-body" id="infoBody"></div>
    <div class="modal-foot"><span class="spacer"></span>
      <button class="btn btn-quiet" id="infoCancel">Close</button>
      <button class="btn btn-primary" id="infoAction">OK</button>
    </div>
  </div>
</div>

<div class="ctx" id="ctx" role="menu"><div class="ctx-head" id="ctxHead"></div><div id="ctxBody"></div></div>
<div class="toasts" id="toasts"></div>
`;
