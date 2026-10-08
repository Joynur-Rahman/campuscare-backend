import json
from app.services.repositories import department_repo, category_repo

CATEGORIES = [
  { "key": 'IT', "label": 'IT & Network', "team": 'IT & Network Cell', "issues": ['Wi-Fi not working', 'Internet very slow', 'LAN port not working', 'Projector not working'] },
  { "key": 'Electrical', "label": 'Electrical', "team": 'Electrical Cell', "issues": ['Fan not working', 'Tube light / bulb not working', 'Power socket not working', 'No power in room'] },
  { "key": 'Water', "label": 'Water & Plumbing', "team": 'Plumbing & Estate', "issues": ['No water supply', 'Tap leaking', 'Flush not working', 'Drain overflowing'] },
  { "key": 'Hostel', "label": 'Hostel Office', "team": 'Hostel Office', "issues": ['Room change request', 'Laundry service issue', 'Noise complaint'] },
  { "key": 'Civil', "label": 'Building & Civil', "team": 'Civil & Building Maintenance', "issues": ['Wall crack', 'Water seepage / damp wall', 'Roof leaking', 'Floor tiles broken'] },
  { "key": 'Housekeeping', "label": 'Cleaning & Pests', "team": 'Housekeeping & Sanitation', "issues": ['Room not cleaned', 'Garbage not collected', 'Cockroaches / rats', 'Mosquito problem'] },
  { "key": 'Mess', "label": 'Mess & Canteen', "team": 'Mess & Food Services', "issues": ['Food quality poor', 'Hygiene issue', 'Menu not followed'] },
  { "key": 'Security', "label": 'Security & Safety', "team": 'Security Office', "issues": ['Theft / item stolen', 'Lost & found', 'Suspicious person on campus', 'Gate / entry problem'] },
  { "key": 'Medical', "label": 'Medical', "team": 'Medical Centre', "issues": ['Need doctor / first aid', 'Ambulance needed', 'Medicine not available'] },
  { "key": 'Other', "label": 'Something else', "team": 'Other', "issues": ['Something else (describe it in the details)'] },
]

for cat in CATEGORIES:
    team_name = cat["team"]
    dept = next((d for d in department_repo.get_all() if d["name"] == team_name), None)
    if not dept:
        department_repo.create(team_name, f"{team_name} Department")
        dept = next((d for d in department_repo.get_all() if d["name"] == team_name), None)
    
    cat_row = next((c for c in category_repo.get_by_department(dept["id"]) if c["name"] == cat["key"]), None)
    if not cat_row:
        category_repo.create(dept["id"], cat["key"], cat["label"])

print("Seeding successful.")
