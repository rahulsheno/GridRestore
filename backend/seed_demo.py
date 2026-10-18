"""Seed a small synthetic scenario into PostgreSQL. Run schema.sql first."""
from .db import connect

NODES = [
 ("S1","North substation","substation",9.0,"North"),
 ("B1","North bus","bus",7.0,"North"),
 ("B2","Central bus","bus",7.5,"Central"),
 ("B3","South bus","bus",6.0,"South"),
 ("H1","Hospital","hospital",10.0,"Central"),
 ("W1","Water facility","water_facility",8.5,"South"),
 ("R1","Residential A","residential",4.0,"North"),
 ("R2","Residential B","residential",4.5,"Central"),
 ("I1","Industrial zone","industrial",5.0,"South"),
]
EDGES = [
 ("E1","S1","B1","feeder",6000),("E2","B1","B2","line",4000),
 ("E3","B2","B3","line",3500),("E4","B2","H1","feeder",1500),
 ("E5","B3","W1","feeder",1200),("E6","B1","R1","feeder",1000),
 ("E7","B2","R2","feeder",1000),("E8","B3","I1","feeder",1800),
 ("E9","B1","B3","tie_line",2500),
]
TASKS = [
 ("T01","E1","Feeder E1",3.0,2200,8.0,2,"North","general"),
 ("T02","E4","Hospital branch E4",5.0,3600,10.0,1,"Central","electrical"),
 ("T03","E3","South line E3",6.0,4200,9.0,1,"South","electrical"),
 ("T04","E6","Residential feeder E6",2.0,1200,4.0,4,"North","general"),
 ("T05","E5","Water facility branch E5",4.0,2800,8.5,2,"South","general"),
 ("T06","E8","Industrial feeder E8",3.5,2400,5.0,3,"South","general"),
 ("T07","E2","Central line E2",4.5,3000,7.0,2,"Central","general"),
 ("T08","E7","Residential feeder E7",2.5,1500,4.5,3,"Central","general"),
]
# (task_id, prerequisite_task_id): repair the upstream line before the branch.
DEPENDENCIES = [("T02","T07"),("T05","T03")]
CREWS = [
 ("C1","Crew 1 (multi-skill)","multi-skill",0),
 ("C2","Crew 2 (general)","general",0),
 ("C3","Crew 3 (general)","general",0),
]
def seed():
    with connect() as c:
        with c.cursor() as cur:
            cur.executemany("INSERT INTO grid_nodes(node_id,node_name,node_type,criticality,region_code) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(node_id) DO NOTHING",NODES)
            cur.executemany("INSERT INTO grid_edges(edge_id,from_node_id,to_node_id,component_type,nominal_capacity_kw) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(edge_id) DO NOTHING",EDGES)
            cur.executemany("INSERT INTO crews(crew_id,crew_name,skill,available_from) VALUES(%s,%s,%s,%s) ON CONFLICT(crew_id) DO NOTHING",CREWS)
            scenario = cur.execute(
              "INSERT INTO outage_scenarios(scenario_name,budget,crew_count) VALUES(%s,%s,%s) RETURNING scenario_id",
              ("Synthetic multi-component outage",14000,3)).fetchone()
            sid = scenario["scenario_id"]
            cur.executemany("""INSERT INTO repair_tasks(task_id,scenario_id,edge_id,component_name,estimated_hours,
              estimated_cost,service_weight,priority,region_code,required_skill,status)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') ON CONFLICT(task_id) DO NOTHING""",
              [(t[0],sid,*t[1:]) for t in TASKS])
            cur.executemany("INSERT INTO task_dependencies(task_id,prerequisite_task_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",DEPENDENCIES)
            return sid
if __name__ == "__main__":
    print("Seeded scenario ID:",seed())
