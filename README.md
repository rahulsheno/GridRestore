# GridRestore

**A power-distribution restoration planning and grid-physics research platform**

GridRestore is an academic project for exploring how power-distribution restoration work can be prioritised after an outage. It combines a web application for dependency-constrained repair scheduling with a separate physics study built around standard IEEE test networks.

The scheduling application models outage scenarios, repair tasks, dependencies, crew skills and budgets. It compares scheduling heuristics, persists runs in PostgreSQL, and supports audit history, scenario versioning and semantic search over repair narratives. The physics study evaluates power-flow behaviour, state estimation, false-data injection and operating-state decisions on IEEE benchmark networks.

> **Scope:** The scheduling application and the IEEE physics study currently use separate data workflows and data models. They are not an integrated operational restoration controller. Project data is synthetic or drawn from published benchmark networks. GridRestore is intended for academic demonstration and research, not real utility operations.

---

## Contents

- [Highlights](#highlights)
- [Application screenshots](#application-screenshots)
- [System architecture](#system-architecture)
- [Entity relationship diagram (Chen's notation)](#entity-relationship-diagram-chens-notation)
- [Relational schema](#relational-schema)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Getting started](#getting-started)
- [Running the application](#running-the-application)
- [Physics study](#physics-study)
- [Testing](#testing)
- [Documentation](#documentation)
- [Security and limitations](#security-and-limitations)

## Highlights

### Restoration planning

- Model synthetic grid nodes, network connections, outage scenarios, repair tasks and repair prerequisites.
- Schedule work against a budget, crew availability, crew skill and task-dependency constraints.
- Compare three scheduling strategies: `priority_first`, `shortest_repair_first` and `gridrestore_score`.
- Compare heuristic outcomes with an exact mixed-integer optimisation baseline on small instances.
- Save restoration runs with task assignments, start/finish times, total cost, makespan and weighted recovery score.
- Inspect critical repairs, downstream unblock counts and critical paths.
- Compare saved runs and export Markdown reports.
- Import and export task data through CSV with row-level validation.

### Database and data integrity

- PostgreSQL relational schema for grid assets, scenarios, tasks, crews, runs and scheduled actions.
- Database constraints for valid references, task values and crew scheduling integrity.
- Crew-overlap prevention using a PostgreSQL exclusion constraint with `btree_gist`.
- Scenario edit history with version comparison and rollback.
- Audit events for changes to important records.
- Run-statistics dashboard backed by a materialized view.

### Similar-repair search

- Store repair narratives alongside vector embeddings using **pgvector**.
- Rank similar repair narratives using cosine distance and an HNSW index.
- Offer PostgreSQL full-text search as a complementary keyword-based mode.
- Support a deterministic hash-based embedder and an optional Sentence Transformers embedding backend.

### Grid-physics research

The separate physics module includes:

- DC power-flow and PTDF calculations.
- AC measurement models and state estimation.
- Newton power-flow and loadability/continuation studies.
- Generator reactive-power-limit handling.
- False-data injection (FDIA) experiments and bad-data detection analysis.
- Cyber-topology modelling and operating-state Markov decision process (MDP) experiments.
- Sensitivity and convergence studies with CSV and PNG outputs.

## Application screenshots

The screenshots below are maintained in `docs/figures/`.

| Application view | Screenshot |
|---|---|
| Main application overview | ![GridRestore application overview](docs/figures/ui-overview.png) |
| Login | ![GridRestore login screen](docs/figures/ui-login.png) |
| Scheduling | ![Repair scheduling interface](docs/figures/ui-scheduling.png) |
| Saved runs | ![Saved restoration runs](docs/figures/ui-saved%20runs.png) |
| Repair search | ![Similar repair search](docs/figures/ui-repair%20search.png) |
| Critical path | ![Critical repair path](docs/figures/ui-critical%20path.png) |
| Grid map | ![Grid map view](docs/figures/ui%20grid%20map.png) |
| Task data | ![Task data view](docs/figures/ui%20task%20data.png) |
| Audit trail | ![Audit trail](docs/figures/ui%20audit%20trail.png) |
| Physics study | ![Physics study results](docs/figures/physics%20study.png) |

## Design decisions and evaluation notes

### Why PostgreSQL and pgvector?

The project uses two data paradigms because the stored information has two different shapes:

- **Relational data belongs in PostgreSQL.** Grid nodes, edges, scenarios, repair tasks, task dependencies, crews, runs and scheduled actions need primary/foreign keys, transactions and database-enforced constraints. The schema also demonstrates triggers, views, materialized views, stored functions and B-tree/GiST indexes.
- **Repair narratives benefit from vector retrieval.** Free-text descriptions of faults are embedded and searched by cosine distance through pgvector. PostgreSQL full-text search is also available for keyword-oriented matching.

The default deterministic hash embedding keeps the demonstration reproducible without requiring a hosted model. An optional Sentence Transformers backend can use `all-MiniLM-L6-v2` when the optional ML dependencies and model are available.

### Measurements documented by the project

The accompanying methodology and performance documents report these results for the project's benchmark setup:

- The `gridrestore_score` heuristic averaged approximately **15% below the exact optimum** across 200 small random instances.
- A composite database index improved the measured scenario query by approximately **5×**.
- The materialized run-statistics view was approximately **50× faster** than the corresponding live aggregate in the reported benchmark.
- Enforcing the crew-overlap exclusion constraint roughly **doubled bulk-insert cost** in that benchmark.

These are measurements from the documented synthetic benchmark, not general performance guarantees. See [docs/METHODOLOGY.md](docs/METHODOLOGY.md) and [docs/PERFORMANCE.md](docs/PERFORMANCE.md) for setup and context.

## System architecture

The scheduling application follows a three-layer architecture:

1. **Frontend:** Next.js application for authentication, scenario management, scheduling, saved runs, search, criticality, grid visualisation, audit and physics results.
2. **Backend:** FastAPI REST service for authentication, business logic, scheduling, analytics, vector search and read-only physics endpoints.
3. **Database:** PostgreSQL for relational data, audit/version history and pgvector-backed repair embeddings.

```mermaid
flowchart TD
    UI["Next.js frontend"] --> API["FastAPI REST API"]
    API --> DB[("PostgreSQL + pgvector")]
    API --> SCHED["Scheduling and optimisation"]
    API --> SEARCH["Vector and full-text search"]
    API --> CRIT["Criticality and dependency analysis"]
    PHY["IEEE physics study"] --> PHYAPI["Physics result storage and read API"]
    PHYAPI --> DB
    NOTEBOOK["Jupyter notebook / SQLite demo"] --> EXP["Learning workflow and plots"]
```

The physics study is exposed to the frontend through read-only API routes. It remains a distinct analytical workflow; the project does not claim a fully validated mapping from each repair task to a physical network element.

## Entity relationship diagram (Chen's notation)

The following diagram represents the GridRestore conceptual and logical data model using **Chen's ER notation**, rendered via Mermaid `flowchart`:

- **Rectangles** `[ENTITY]` represent **Entity Sets** (with double rectangles `[[WEAK]]` for **Weak Entities**).
- **Diamonds** `{RELATIONSHIP}` represent **Relationships** linking entities.
- **Ovals / Stadiums** `([attribute])` represent **Attributes**, with underlined labels `<u>attribute</u>` denoting **Primary Keys**.
- **Attributes attached to Diamonds** (e.g. `start_hour`, `finish_hour`, `crew_label` on `SCHEDULES`) represent associative attributes of the M:N relationship (the `scheduled_actions` table).
- **Line annotations** (`1`, `N`, `M`) indicate cardinality and structural constraints.

```mermaid
flowchart TD
    %% ==========================================
    %% 1. GRID TOPOLOGY & RESTORATION PLANNING
    %% ==========================================
    subgraph TOPOLOGY["1. Grid Topology & Core Scheduling"]
        direction TB

        %% Entities (Rectangles)
        E_NODE["GRID_NODES"]
        E_EDGE["GRID_EDGES"]
        E_SCENARIO["OUTAGE_SCENARIOS"]
        E_TASK["REPAIR_TASKS"]
        E_RUN["RESTORATION_RUNS"]
        E_CREW["CREWS"]

        %% Relationships (Diamonds)
        R_CONNECTS{"CONNECTS"}
        R_REPAIRS{"REPAIRS"}
        R_CONTAINS{"CONTAINS"}
        R_EVALUATES{"EVALUATES"}
        R_DEPENDS{"PREREQUISITE_FOR"}
        R_SCHEDULES{"SCHEDULES<br/><i>(scheduled_actions)</i>"}

        %% GRID_NODES Attributes
        A_N_ID(["<u>node_id</u>"])
        A_N_NAME(["node_name"])
        A_N_TYPE(["node_type"])
        A_N_CRIT(["criticality"])
        E_NODE --- A_N_ID
        E_NODE --- A_N_NAME
        E_NODE --- A_N_TYPE
        E_NODE --- A_N_CRIT

        %% GRID_EDGES Attributes
        A_E_ID(["<u>edge_id</u>"])
        A_E_TYPE(["component_type"])
        A_E_CAP(["nominal_capacity_kw"])
        E_EDGE --- A_E_ID
        E_EDGE --- A_E_TYPE
        E_EDGE --- A_E_CAP

        %% OUTAGE_SCENARIOS Attributes
        A_S_ID(["<u>scenario_id</u>"])
        A_S_BUDGET(["budget"])
        A_S_CREWS(["crew_count"])
        E_SCENARIO --- A_S_ID
        E_SCENARIO --- A_S_BUDGET
        E_SCENARIO --- A_S_CREWS

        %% REPAIR_TASKS Attributes
        A_T_ID(["<u>task_id</u>"])
        A_T_HOURS(["estimated_hours"])
        A_T_COST(["estimated_cost"])
        A_T_PRIO(["priority"])
        A_T_STATUS(["status"])
        E_TASK --- A_T_ID
        E_TASK --- A_T_HOURS
        E_TASK --- A_T_COST
        E_TASK --- A_T_PRIO
        E_TASK --- A_T_STATUS

        %% CREWS Attributes
        A_C_ID(["<u>crew_id</u>"])
        A_C_NAME(["crew_name"])
        A_C_SKILL(["skill"])
        E_CREW --- A_C_ID
        E_CREW --- A_C_NAME
        E_CREW --- A_C_SKILL

        %% RESTORATION_RUNS Attributes
        A_R_ID(["<u>run_id</u>"])
        A_R_STRAT(["strategy_name"])
        A_R_COST(["total_cost"])
        A_R_MAKE(["makespan_hours"])
        E_RUN --- A_R_ID
        E_RUN --- A_R_STRAT
        E_RUN --- A_R_COST
        E_RUN --- A_R_MAKE

        %% Relationship Attributes on SCHEDULES (Associative attributes in Chen notation)
        A_SCHED_ACT(["<u>action_id</u>"])
        A_SCHED_START(["start_hour"])
        A_SCHED_FINISH(["finish_hour"])
        A_SCHED_CREW(["crew_label"])
        R_SCHEDULES --- A_SCHED_ACT
        R_SCHEDULES --- A_SCHED_START
        R_SCHEDULES --- A_SCHED_FINISH
        R_SCHEDULES --- A_SCHED_CREW

        %% Relationships & Cardinalities
        E_NODE -- "1:from" --- R_CONNECTS
        E_NODE -- "1:to" --- R_CONNECTS
        R_CONNECTS -- "N" --- E_EDGE

        E_EDGE -- "1" --- R_REPAIRS
        R_REPAIRS -- "N" --- E_TASK

        E_SCENARIO -- "1" --- R_CONTAINS
        R_CONTAINS -- "N" --- E_TASK

        E_SCENARIO -- "1" --- R_EVALUATES
        R_EVALUATES -- "N" --- E_RUN

        E_RUN -- "M" --- R_SCHEDULES
        R_SCHEDULES -- "N" --- E_TASK

        %% Unary / Recursive relationship
        E_TASK -- "1:prereq" --- R_DEPENDS
        R_DEPENDS -- "N:dependent" --- E_TASK
    end

    %% ==========================================
    %% 2. IDENTITY, AUDIT & VERSION HISTORY
    %% ==========================================
    subgraph IDENTITY["2. Identity, Audit & History"]
        direction TB

        E_USER["APP_USERS"]
        E_TOKEN["REFRESH_TOKENS"]
        E_VER[["SCENARIO_VERSIONS"]]
        E_AUDIT["AUDIT_LOG"]

        R_AUTH{"AUTHENTICATES"}
        R_VERSION{"HAS_VERSION"}
        R_AUDITS{"LOGS_CHANGES"}

        %% APP_USERS Attributes
        A_U_ID(["<u>user_id</u>"])
        A_U_NAME(["username"])
        A_U_ROLE(["role"])
        E_USER --- A_U_ID
        E_USER --- A_U_NAME
        E_USER --- A_U_ROLE

        %% REFRESH_TOKENS Attributes
        A_TOK_HASH(["<u>token_hash</u>"])
        A_TOK_EXP(["expires_at"])
        E_TOKEN --- A_TOK_HASH
        E_TOKEN --- A_TOK_EXP

        %% SCENARIO_VERSIONS Attributes (Weak Entity)
        A_V_NUM(["<u>version_no</u>"])
        A_V_DATA(["snapshot_data"])
        E_VER --- A_V_NUM
        E_VER --- A_V_DATA

        %% AUDIT_LOG Attributes
        A_AL_ID(["<u>audit_id</u>"])
        A_AL_TAB(["table_name"])
        A_AL_OP(["operation"])
        A_AL_ROW(["row_key"])
        E_AUDIT --- A_AL_ID
        E_AUDIT --- A_AL_TAB
        E_AUDIT --- A_AL_OP
        E_AUDIT --- A_AL_ROW

        %% Connections
        E_USER -- "1" --- R_AUTH
        R_AUTH -- "N" --- E_TOKEN

        E_SCENARIO -- "1" --- R_VERSION
        R_VERSION -- "N" --- E_VER

        E_TASK -.->|"polymorphic"| R_AUDITS
        E_SCENARIO -.->|"polymorphic"| R_AUDITS
        R_AUDITS -->|"N"| E_AUDIT
    end

    %% ==========================================
    %% 3. SEARCH & PHYSICS BRIDGE
    %% ==========================================
    subgraph SEARCH_BRIDGE["3. Search & Grid-to-Physics Bridge"]
        direction TB

        E_EMBED[["REPAIR_EMBEDDINGS"]]
        E_EPM[["ELEMENT_PHYSICS_MAP"]]

        R_EMBEDS{"HAS_EMBEDDING"}
        R_MAPS{"MAPS_TO"}

        %% REPAIR_EMBEDDINGS Attributes
        A_EMB_V32(["embedding: vector(32)"])
        A_EMB_V384(["embedding_st: vector(384)"])
        A_EMB_TSV(["narrative_tsv"])
        E_EMBED --- A_EMB_V32
        E_EMBED --- A_EMB_V384
        E_EMBED --- A_EMB_TSV

        %% ELEMENT_PHYSICS_MAP Attributes
        A_EPM_CASE(["case_name"])
        A_EPM_TYPE(["element_type"])
        A_EPM_IDX(["element_index"])
        E_EPM --- A_EPM_CASE
        E_EPM --- A_EPM_TYPE
        E_EPM --- A_EPM_IDX

        %% Connections
        E_TASK -- "1" --- R_EMBEDS
        R_EMBEDS -- "0..1" --- E_EMBED

        E_EDGE -- "1" --- R_MAPS
        R_MAPS -- "0..1" --- E_EPM
    end

    %% ==========================================
    %% 4. PHYSICS-STUDY RESULT RELATIONS
    %% ==========================================
    subgraph PHYSICS_STUDY["4. Physics-Study Result Models"]
        direction TB

        E_PR["PHYSICS_RUNS"]
        R_PRODUCES{"PRODUCES"}

        %% Weak Result Entities
        W_PVAL[["PHYSICS_VALIDATION"]]
        W_PCONT[["PHYSICS_CONTINUATION"]]
        W_PCONTSUM[["PHYSICS_CONTINUATION_SUMMARY"]]
        W_PFDIASUM[["PHYSICS_FDIA_SUMMARY"]]
        W_PFDIATRI[["PHYSICS_FDIA_TRIALS"]]
        W_PMDPPOL[["PHYSICS_MDP_POLICY"]]
        W_PMDPTR[["PHYSICS_MDP_TRANSITIONS"]]
        W_PSENS[["PHYSICS_SENSITIVITY"]]
        W_PCONV[["PHYSICS_CONVERGENCE"]]
        W_PFIG[["PHYSICS_FIGURES"]]

        %% PHYSICS_RUNS Attributes
        A_PR_ID(["<u>run_id</u>"])
        A_PR_MODE(["mode"])
        A_PR_SETT(["settings"])
        E_PR --- A_PR_ID
        E_PR --- A_PR_MODE
        E_PR --- A_PR_SETT

        %% Results link through identifying relationship PRODUCES
        E_PR -- "1" --- R_PRODUCES
        R_PRODUCES -- "N" --- W_PVAL
        R_PRODUCES -- "N" --- W_PCONT
        R_PRODUCES -- "N" --- W_PCONTSUM
        R_PRODUCES -- "N" --- W_PFDIASUM
        R_PRODUCES -- "N" --- W_PFDIATRI
        R_PRODUCES -- "N" --- W_PMDPPOL
        R_PRODUCES -- "N" --- W_PMDPTR
        R_PRODUCES -- "N" --- W_PSENS
        R_PRODUCES -- "N" --- W_PCONV
        R_PRODUCES -- "N" --- W_PFIG
    end

    %% Inter-subgraph links
    E_SCENARIO -.->|references| E_VER
    E_TASK -.->|references| E_EMBED
    E_EDGE -.->|references| E_EPM

    %% ==========================================
    %% CHEN NOTATION STYLING (Charcoal & Silver Theme)
    %% ==========================================
    classDef entity fill:#20262e,stroke:#aab4c0,stroke-width:1.2px,color:#f5f7fa;
    classDef weakEntity fill:#20262e,stroke:#aab4c0,stroke-width:1.5px,stroke-dasharray:4 2,color:#f5f7fa;
    classDef relationship fill:#252a32,stroke:#aab4c0,stroke-width:1.2px,color:#f5f7fa;
    classDef attribute fill:#181b20,stroke:#8b949e,stroke-width:1px,color:#dce3ea;

    class E_NODE,E_EDGE,E_SCENARIO,E_TASK,E_RUN,E_CREW,E_USER,E_TOKEN,E_AUDIT,E_PR entity;
    class E_VER,E_EMBED,E_EPM,W_PVAL,W_PCONT,W_PCONTSUM,W_PFDIASUM,W_PFDIATRI,W_PMDPPOL,W_PMDPTR,W_PSENS,W_PCONV,W_PFIG weakEntity;
    class R_CONNECTS,R_REPAIRS,R_CONTAINS,R_EVALUATES,R_DEPENDS,R_SCHEDULES,R_AUTH,R_VERSION,R_AUDITS,R_EMBEDS,R_MAPS,R_PRODUCES relationship;
    class A_N_ID,A_N_NAME,A_N_TYPE,A_N_CRIT,A_E_ID,A_E_TYPE,A_E_CAP,A_S_ID,A_S_BUDGET,A_S_CREWS,A_T_ID,A_T_HOURS,A_T_COST,A_T_PRIO,A_T_STATUS,A_C_ID,A_C_NAME,A_C_SKILL,A_R_ID,A_R_STRAT,A_R_COST,A_R_MAKE,A_SCHED_ACT,A_SCHED_START,A_SCHED_FINISH,A_SCHED_CREW,A_U_ID,A_U_NAME,A_U_ROLE,A_TOK_HASH,A_TOK_EXP,A_V_NUM,A_V_DATA,A_AL_ID,A_AL_TAB,A_AL_OP,A_AL_ROW,A_EMB_V32,A_EMB_V384,A_EMB_TSV,A_EPM_CASE,A_EPM_TYPE,A_EPM_IDX,A_PR_ID,A_PR_MODE,A_PR_SETT attribute;
    linkStyle default stroke:#9aa6b2,stroke-width:1.2px;
```

**Relationship and constraint notes:** `task_dependencies` uses a composite primary key and two foreign keys to `repair_tasks`. `grid_edges` has two separate foreign keys to `grid_nodes`. `scheduled_actions` prevents overlapping time ranges for the same crew within a run using a PostgreSQL exclusion constraint; the crew is identified by the text `crew_label`, not `crews.crew_id`. `audit_log` stores polymorphic table/row references rather than foreign keys to every audited table. Physics result tables reference `physics_runs`; `element_physics_map` references `grid_edges` but does not reference `physics_runs`.

The diagram is a schema overview. For complete column definitions, data types, and constraint details, see [docs/ERD.md](docs/ERD.md) and [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md). The original detailed ERD images remain in [`docs/figures/ER Diagram/`](docs/figures/ER%20Diagram/).

## Relational schema

The following section documents the **25 relations** mapped from the conceptual Chen ER model. It includes the visual **Elmasri–Navathe Relational Schema Diagram** showing table structures and foreign-key dependencies, followed by the table-by-table relational schema notation.

### Relational schema diagram (Referential Integrity Constraints)

The following schema diagram represents the GridRestore relational database using the **Elmasri–Navathe relational schema format**: each relation is displayed with its relation name on top, attributes arranged horizontally in contiguous cells with **Primary Keys underlined**, and directed referential integrity arrows pointing from each **Foreign Key** directly into the referenced **Primary Key**.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/figures/relational_schema_diagram.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/figures/relational_schema_diagram_light.png">
    <img alt="GridRestore Relational Database Schema (Elmasri–Navathe Notation)" src="docs/figures/relational_schema_diagram.png" width="100%">
  </picture>
</p>

*Available diagram formats: [High-Resolution Dark Theme PNG](docs/figures/relational_schema_diagram.png) • [Textbook Light Theme PNG](docs/figures/relational_schema_diagram_light.png) • [Vector Dark SVG](docs/figures/relational_schema_diagram.svg) • [Vector Light SVG](docs/figures/relational_schema_diagram_light.svg)*

### Table-by-table relation notation

The following relational schema documents the **25 relations** and lists the primary keys (PK), foreign keys (FK), composite keys, and constraints represented in the diagram above.

**Notation**
- `PK` — primary key.
- `FK` — foreign key; the target relation and attribute are shown after `→`.
- `UQ` — unique constraint.
- `CHECK` — check constraint.
- A composite key is shown as `PK (attribute_1, attribute_2, ...)`.

> **Scope note:** The Mermaid flowchart is a schema overview, not a full data dictionary. It does not show every non-key column or every SQL data type. Accordingly, the relation definitions below include the attributes and constraints actually named in the flowchart and its relationship notes. Unshown attributes are not inferred.

---

### 1. Grid topology

```text
GRID_NODES(
    node_id          PK,
    node_name,
    node_type,
    criticality,
    region_code
)

GRID_EDGES(
    edge_id          PK,
    from_node_id     FK → GRID_NODES(node_id),
    to_node_id       FK → GRID_NODES(node_id),
    UQ (from_node_id, to_node_id)
)
```

### 2. Restoration planning and scheduling

```text
OUTAGE_SCENARIOS(
    scenario_id      PK,
    budget,
    crew_count,
    created_at
)

REPAIR_TASKS(
    task_id          PK,
    scenario_id      FK → OUTAGE_SCENARIOS(scenario_id),
    edge_id          FK → GRID_EDGES(edge_id),
    hours,
    cost,
    priority,
    status,
    CHECK (hours > 0),
    CHECK (status is a valid workflow status)
)

TASK_DEPENDENCIES(
    task_id              PK, FK → REPAIR_TASKS(task_id),
    prerequisite_task_id PK, FK → REPAIR_TASKS(task_id),
    PK (task_id, prerequisite_task_id),
    CHECK (task_id <> prerequisite_task_id)
)

CREWS(
    crew_id          PK,
    crew_name,
    skill,
    available_from
)

RESTORATION_RUNS(
    run_id           PK,
    scenario_id      FK → OUTAGE_SCENARIOS(scenario_id),
    strategy_name,
    total_cost,
    makespan
)

SCHEDULED_ACTIONS(
    action_id        PK,
    run_id           FK → RESTORATION_RUNS(run_id),
    task_id          FK → REPAIR_TASKS(task_id),
    crew_label,
    start_hour,
    finish_hour,
    UQ (run_id, task_id),
    CHECK (finish_hour > start_hour)
)
```

### 3. Identity, audit, and scenario history

```text
APP_USERS(
    user_id          PK,
    username         UQ,
    role,
    CHECK (role IN ('admin', 'operator'))
)

REFRESH_TOKENS(
    token_hash       PK,
    username         FK → APP_USERS(username),
    expires_at,
    revoked
)

SCENARIO_VERSIONS(
    scenario_id      PK, FK → OUTAGE_SCENARIOS(scenario_id),
    version_no       PK,
    PK (scenario_id, version_no),
    CHECK (version_no >= 1)
)

AUDIT_LOG(
    audit_id         PK,
    table_name,
    operation,
    row_key,
    old_data,
    new_data,
    app_user
)
```

`AUDIT_LOG` uses the polymorphic pair `table_name` + `row_key`; the ERD does not define a conventional foreign key from this relation to every audited table.

### 4. Semantic repair search

```text
REPAIR_EMBEDDINGS(
    task_id          PK, FK → REPAIR_TASKS(task_id),
    embedding,       -- vector(32)
    embedding_st,    -- vector(384), optional
    narrative_tsv    -- generated tsvector
)
```

The ERD identifies `REPAIR_EMBEDDINGS.task_id` as both its primary key and its foreign key to `REPAIR_TASKS`, giving a one-to-zero-or-one relationship.

### 5. Grid-to-physics mapping

```text
ELEMENT_PHYSICS_MAP(
    edge_id          PK, FK → GRID_EDGES(edge_id),
    case_name,
    element_type,
    element_index,
    CHECK (case_name is a supported IEEE case),
    CHECK (element_type is a supported element type),
    CHECK (element_index >= 0)
)
```

The IEEE case and element identifiers are stored as values. The ERD does not define a foreign key from `ELEMENT_PHYSICS_MAP` to `PHYSICS_RUNS`.

### 6. Physics-study runs and result relations

The flowchart explicitly identifies the following key attributes and the foreign key to `PHYSICS_RUNS`. It does not list the remaining non-key result attributes for these tables.

```text
PHYSICS_RUNS(
    run_id           PK,
    mode,
    headline_weights,
    plan_weights,
    settings,
    created_at
)

PHYSICS_VALIDATION(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    check_name       PK,
    case_name        PK,
    metric           PK,
    PK (run_id, check_name, case_name, metric)
)

PHYSICS_CONTINUATION(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    alpha            PK,
    PK (run_id, case_name, alpha)
)

PHYSICS_CONTINUATION_SUMMARY(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    PK (run_id, case_name)
)

PHYSICS_FDIA_SUMMARY(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    kind             PK,
    PK (run_id, case_name, kind),
    CHECK (kind IN ('dc', 'ac', 'lnr', 'targeted'))
)

PHYSICS_FDIA_TRIALS(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    trial            PK,
    PK (run_id, case_name, trial)
)

PHYSICS_MDP_POLICY(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    stress_vector    PK,
    weight_set       PK,
    state            PK,
    PK (run_id, case_name, stress_vector, weight_set, state)
)

PHYSICS_MDP_TRANSITIONS(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    stress_vector    PK,
    collapse_model   PK,
    action           PK,
    PK (run_id, case_name, stress_vector, collapse_model, action)
)

PHYSICS_SENSITIVITY(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    sweep            PK,
    k                PK,
    lambda0          PK,
    w1               PK,
    w3               PK,
    k_voltage        PK,
    gamma            PK,
    PK (run_id, sweep, k, lambda0, w1, w3, k_voltage, gamma)
)

PHYSICS_CONVERGENCE(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    case_name        PK,
    stress_vector    PK,
    method           PK,
    step             PK,
    PK (run_id, case_name, stress_vector, method, step)
)

PHYSICS_FIGURES(
    run_id           PK, FK → PHYSICS_RUNS(run_id),
    name             PK,
    PK (run_id, name)
)
```

---

### 7. Relationship summary

| Parent relation | Child relation | Cardinality | Linking attribute(s) |
|---|---|---:|---|
| `GRID_NODES` | `GRID_EDGES` | 1 : many | `from_node_id` |
| `GRID_NODES` | `GRID_EDGES` | 1 : many | `to_node_id` |
| `OUTAGE_SCENARIOS` | `REPAIR_TASKS` | 1 : many | `scenario_id` |
| `GRID_EDGES` | `REPAIR_TASKS` | 1 : many | `edge_id` |
| `REPAIR_TASKS` | `TASK_DEPENDENCIES` | 1 : many | `task_id` (dependent task) |
| `REPAIR_TASKS` | `TASK_DEPENDENCIES` | 1 : many | `prerequisite_task_id` (prerequisite) |
| `OUTAGE_SCENARIOS` | `RESTORATION_RUNS` | 1 : many | `scenario_id` |
| `RESTORATION_RUNS` | `SCHEDULED_ACTIONS` | 1 : many | `run_id` |
| `REPAIR_TASKS` | `SCHEDULED_ACTIONS` | 1 : many | `task_id` |
| `APP_USERS` | `REFRESH_TOKENS` | 1 : many | `username` |
| `OUTAGE_SCENARIOS` | `SCENARIO_VERSIONS` | 1 : many | `scenario_id` |
| `REPAIR_TASKS` | `REPAIR_EMBEDDINGS` | 1 : 0..1 | `task_id` |
| `GRID_EDGES` | `ELEMENT_PHYSICS_MAP` | 1 : 0..1 | `edge_id` |
| `PHYSICS_RUNS` | Each of the 10 physics result relations | 1 : many | `run_id` |

### 8. Important integrity rules and non-FK references

1. `GRID_EDGES` has two foreign keys to `GRID_NODES`, one for each endpoint, and a unique constraint on `(from_node_id, to_node_id)`.
2. `TASK_DEPENDENCIES` has a composite primary key and two foreign keys to `REPAIR_TASKS`; a task cannot depend on itself.
3. `SCHEDULED_ACTIONS` has a unique constraint on `(run_id, task_id)` and a check requiring `finish_hour > start_hour`.
4. Crew assignment in `SCHEDULED_ACTIONS` is stored in `crew_label` as text. It is **not** a foreign key to `CREWS.crew_id`. The schema overview also notes a crew-overlap exclusion constraint within a restoration run.
5. `AUDIT_LOG` stores polymorphic references (`table_name` and `row_key`) rather than foreign keys to all audited relations.
6. `ELEMENT_PHYSICS_MAP.edge_id` references `GRID_EDGES.edge_id`; the IEEE case and element identifiers are values, not references to `PHYSICS_RUNS`.
7. Each physics result relation references `PHYSICS_RUNS.run_id`; its result-specific composite primary key is shown above.

---

**Source:** The Mermaid flowchart and its relationship/constraint notes in the GridRestore `README.md`. For complete column definitions and SQL data types, consult the repository's `docs/ERD.md` and `database/schema.sql` plus migrations; those details are not fully represented in the Mermaid ERD itself.

## Technology stack

| Layer | Technologies |
|---|---|
| Frontend | Next.js, React, TypeScript |
| Backend API | Python, FastAPI, Uvicorn, Pydantic |
| Relational database | PostgreSQL |
| Vector search | pgvector, HNSW cosine similarity, PostgreSQL full-text search |
| Authentication | bcrypt password hashing, signed access tokens, refresh-token handling, role checks |
| Scheduling and analytics | NumPy, pandas, SciPy, PuLP, NetworkX |
| Power-system analysis | pandapower and project power-flow/state-estimation modules |
| Visualisation and research | Matplotlib, Jupyter Notebook |
| Tests | pytest, pytest-cov |
| Containerisation | Docker Compose |

Optional transformer embeddings can be installed separately using `requirements-ml.txt`. PostgreSQL itself and its required extensions must be installed or provided by the database service.

## Repository structure

The tree below highlights the main source files and supporting project artefacts. Individual test modules and generated result files are grouped to keep the overview readable.

```text
GridRestore/
├── backend/
│   ├── api.py                    # FastAPI application and REST endpoints
│   ├── auth.py                   # Authentication, roles and token handling
│   ├── db.py                     # PostgreSQL access and persistence
│   ├── scheduler.py              # Budget/skill/dependency-aware heuristics
│   ├── exact.py                  # Exact optimisation baseline
│   ├── criticality.py            # Critical repairs and critical-path analysis
│   ├── analytics.py              # Sweeps, robustness and performance analytics
│   ├── audit_dashboard.py        # Audit and dashboard data
│   ├── diffing.py                # Compare saved restoration runs
│   ├── report.py                 # Markdown run reports
│   ├── tasks_io.py               # CSV import/export and validation
│   ├── versions.py               # Scenario version history and rollback
│   ├── vectors.py                # Embeddings, pgvector and full-text search
│   ├── embeddings.py             # Hash and Sentence Transformers backends
│   ├── physics_api.py            # Read-only physics result endpoints
│   ├── physics_map.py            # Physics-to-planning weighting support
│   ├── seed_demo.py              # Demo scenario seed
│   ├── seed_users.py             # Demo user seed
│   └── grid/
│       ├── ac_se.py              # AC measurement model and state estimation
│       ├── dc_model.py           # DC network model and PTDF
│       ├── pflow.py              # Power-flow solver and branch tracing
│       ├── operating_point.py    # Load continuation and operating points
│       ├── fdia.py               # False-data injection experiments
│       ├── cyber.py              # Cyber topology model
│       ├── mdp.py                # Operating-state MDP
│       ├── dispatch.py            # Dispatch calculations
│       ├── study.py               # Physics study calculations
│       ├── store.py               # Physics study persistence
│       └── physics_study.py       # Study driver and artifact generation
├── database/
│   ├── schema.sql                 # Core relational schema
│   ├── lab_queries.sql            # SQL learning and demonstration queries
│   ├── performance_queries.sql    # EXPLAIN ANALYZE examples
│   └── migrations/
│       ├── 002_vectors.sql
│       ├── 003_auth.sql
│       ├── 004_causes.sql
│       ├── 005_integrity_audit_versions.sql
│       ├── 006_physics.sql
│       ├── 007_physics_extensions.sql
│       ├── 008_auth_hardening.sql
│       ├── 009_embeddings_st.sql
│       └── 010_element_physics_map.sql
├── docker/
│   └── init/                      # Ordered PostgreSQL initialisation scripts
├── docs/
│   ├── figures/                   # Application screenshots and split ER diagrams
│   ├── physics/                   # Physics CSV results and plots
│   ├── ARCHITECTURE.md
│   ├── ERD.md
│   ├── IMPLEMENTATION_NOTES.md
│   ├── METHODOLOGY.md
│   ├── PERFORMANCE.md
│   ├── PHYSICS.md
│   ├── PROJECT_OVERVIEW.md
│   ├── PROJECT_REPORT.md
│   ├── RUNNING.md
│   ├── STANDARDS.md
│   └── TESTING.md
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Main application interface
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── AuditPanel.tsx
│   │   ├── GridPanel.tsx
│   │   ├── GridScene.tsx
│   │   ├── PhysicsPanel.tsx
│   │   ├── TaskDataPanel.tsx
│   │   ├── ThemeToggle.tsx
│   │   ├── icons.tsx
│   │   └── ui.tsx
│   └── lib/
│       ├── api-client.ts
│       └── api-types.ts
├── notebook/
│   └── GridRestore_Lab.ipynb       # Standalone learning/demo notebook
├── scripts/
│   ├── setup_db.sh
│   └── sync_docker_init.sh
├── tests/                          # Automated API, DB, scheduler and physics tests
├── .env.example
├── docker-compose.yml
├── Dockerfile.api
├── pytest.ini
├── requirements.txt
├── requirements-ml.txt
└── README.md
```

## Getting started

### Prerequisites

- Python 3.12 recommended.
- Node.js 20 or later for the frontend.
- PostgreSQL 16 or 18 with the `pgvector` and `btree_gist` extensions available.
- PostgreSQL command-line tools (`psql`).
- Git.

### 1. Clone the repository

```bash
git clone https://github.com/rahulsheno/GridRestore.git
cd GridRestore
```

### 2. Create and activate a Python environment

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux/macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example file:

**PowerShell**
```powershell
Copy-Item .env.example .env
```

**Linux/macOS**
```bash
cp .env.example .env
```

Set the database connection string and a long, random session secret in your local environment or `.env` file:

```env
DATABASE_URL=postgresql://gridrestore_user:YOUR_PASSWORD@localhost:5432/gridrestore
SESSION_SECRET=replace-with-a-long-random-secret
```

Do not commit your real `.env` file or credentials.

### 4. Create the PostgreSQL database

Connect as a PostgreSQL administrator and create a database role and database:

```sql
CREATE USER gridrestore_user WITH PASSWORD 'YOUR_PASSWORD';
CREATE DATABASE gridrestore OWNER gridrestore_user;
```

Then set `DATABASE_URL` to use this role and database.

### 5. Initialise the schema and demo data

From the repository root, run the setup script in a Bash-compatible shell (Linux, macOS, WSL or Git Bash):

```bash
./scripts/setup_db.sh
```

The script applies the database schema and migrations and loads demo data. Use `--reset` only when you intentionally want to rebuild the target schema; it is destructive to existing objects in that schema. For Windows-specific PostgreSQL setup details, see [docs/RUNNING.md](docs/RUNNING.md).

## Running the application

Start the services in separate terminals.

### Terminal 1 — FastAPI backend

From the repository root:

```bash
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

- API base: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### Terminal 2 — Next.js frontend

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

For a production build:

```bash
npm run build
npm run start
```

### Demo accounts

The local demo seed uses the accounts below by default. Change their passwords before using the application outside a local demonstration.

| Role | Username | Password | Permissions |
|---|---|---|---|
| Administrator | `admin` | `admin123` | Manage data, scenarios, versions and audit functions |
| Operator | `operator` | `operator123` | View data, run schedules and analytics |

### Docker Compose

The repository includes a Docker Compose stack for PostgreSQL/pgvector and the API, plus a one-shot seed service. The compose database is mapped to host port **5433** to avoid conflicting with a local PostgreSQL service on port 5432.

```bash
SESSION_SECRET="$(openssl rand -hex 32)" docker compose up --build
```

The frontend can be run separately using the steps above. Review `docker-compose.yml` and [docs/RUNNING.md](docs/RUNNING.md) for configuration details before starting the stack.

## Physics study

The physics study uses IEEE benchmark networks bundled with pandapower: case9, case14, case30, case57 and case118.

Run the full study from the repository root:

```bash
python -m backend.grid.physics_study
```

Useful variants:

```bash
python -m backend.grid.physics_study --quick     # reduced Monte Carlo trials
python -m backend.grid.physics_study --no-db     # write files without storing a DB run
python -m backend.grid.physics_study --keep-runs 1
```

Results are written under `docs/physics/` and, unless `--no-db` is supplied, stored in PostgreSQL for display in the application's Physics tab. See [docs/PHYSICS.md](docs/PHYSICS.md) for the assumptions, validation approach, corrections and known limitations.

## Testing

Run tests from the repository root. Database-dependent tests require a configured PostgreSQL database and the environment variables above.

```bash
python -m pytest -q
```

With coverage:

```bash
python -m pytest -q --cov=backend --cov-report=term
```

For focused tests and troubleshooting, see [docs/RUNNING.md](docs/RUNNING.md) and [docs/TESTING.md](docs/TESTING.md).

## Documentation

| Document | Description |
|---|---|
| [Project overview](docs/PROJECT_OVERVIEW.md) | Problem, scope, application/physics split and project status |
| [Project report](docs/PROJECT_REPORT.md) | Objectives, requirements, schema, architecture, results and future work |
| [Architecture](docs/ARCHITECTURE.md) | Application components and data flow |
| [ER diagram and data dictionary](docs/ERD.md) | Entity relationships, tables, keys and constraints |
| [Running guide](docs/RUNNING.md) | Detailed setup, execution, testing and troubleshooting |
| [Methodology](docs/METHODOLOGY.md) | Scheduling methodology and comparison with the exact baseline |
| [Performance](docs/PERFORMANCE.md) | Database indexes, materialized-view and benchmark results |
| [Physics study](docs/PHYSICS.md) | IEEE models, validation, FDIA, MDP and assumptions |
| [Testing](docs/TESTING.md) | Test organisation, coverage and verification notes |
| [Standards and scope](docs/STANDARDS.md) | Standards context and explicit non-compliance claims |

## Security and limitations

- All application outage, network, repair, crew, cost and outcome data is synthetic. Physics experiments use published IEEE benchmark networks.
- GridRestore is not connected to utility infrastructure and must not be used to operate or control electrical equipment.
- The scheduling heuristics are approximations. The exact optimisation baseline is intended for small-instance comparison.
- The power-system models and thresholds are research assumptions; they do not establish regulatory or standards compliance.
- The scheduling application and physics study currently have distinct data workflows and should not be interpreted as a single validated end-to-end grid-restoration model.
- Demo credentials are for local evaluation only. Use unique passwords and a securely generated `SESSION_SECRET` for any non-demo deployment.

---

## Contributors

| Contributor | Role | Key Areas |
|---|---|---|
| [**Rahul Shenoy**](https://github.com/rahulsheno) | Backend & Data Engineering | Backend API, database schema & migrations, grid physics engine, scheduling algorithms, test suite, documentation |
| [**Samvit Nandakishore Atur**](https://github.com/samvitOK) | Frontend Development | Next.js frontend, UI components, grid visualization, physics panel, audit trail dashboard, README & screenshots |

---

For implementation details and project notes, start with [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

