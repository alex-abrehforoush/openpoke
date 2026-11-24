Model: `nvidia/nemotron-3-ultra-550b-a55b:free`, roster of 300 agents, 20 cases, temperature 0.

| Version | recent | keyword | paraphrase | new | Correct | Duplicates | Wrong agent | No call | Prompt tokens (mean) |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 4/4 | 6/6 | 4/4 | 6/6 | 20/20 | 0 | 0 | 0 | 5,978 |
| fixed | 4/4 | 6/6 | 0/4 | 6/6 | 16/20 | 3 | 1 | 0 | 3,569 |

| Case | Expected | Baseline picked | Fixed picked |
|---|---|---|---|
| recent-send | Email to Landlord | Email to Landlord (correct) | Email to Landlord (correct) |
| recent-time | Gym Reminder | Gym Reminder (correct) | Gym Reminder (correct) |
| recent-choice | Mom Birthday Gift | Mom Birthday Gift (correct) | Mom Birthday Gift (correct) |
| recent-add | Weekly Team Sync | Weekly Team Sync (correct) | Weekly Team Sync (correct) |
| keyword-deposit | Email to Priya | Email to Priya (correct) | Email to Priya (correct) |
| keyword-flight | Flight to Lisbon | Flight to Lisbon (correct) | Flight to Lisbon (correct) |
| keyword-visa | Visa Appointment | Visa Appointment (correct) | Visa Appointment (correct) |
| keyword-tax | Tax Documents | Tax Documents (correct) | Tax Documents (correct) |
| keyword-insurance | Car Insurance Renewal | Car Insurance Renewal (correct) | Car Insurance Renewal (correct) |
| keyword-hydro | Electricity Bill | Electricity Bill (correct) | Electricity Bill (correct) |
| paraphrase-teeth | Dentist Appointment | Dentist Appointment (correct) | Dental Appointment Check (duplicate) |
| paraphrase-job | Northwind Offer Letter | Northwind Offer Letter (correct) | Recruiter Follow-up (wrong agent) |
| paraphrase-delivery | Package Tracking | Package Tracking (correct) | Office Order Tracking (duplicate) |
| paraphrase-reading | Book Club | Book Club (correct) | Reading Group Check (duplicate) |
| new-restaurant | (new agent) | Find Italian Restaurant (correct) | Italian Restaurant Search (correct) |
| new-plants | (new agent) | Plant Watering Reminder (correct) | Plant Watering Reminder (correct) |
| new-library | (new agent) | Library Hours Lookup (correct) | Library Hours Check (correct) |
| new-weather | (new agent) | Montreal Weather Check (correct) | Montreal Weather Check (correct) |
| new-drive | (new agent) | General Knowledge (correct) | Toronto to Ottawa Drive (correct) |
| new-spanish | (new agent) | Spanish Class Search (correct) | Spanish Class Search (correct) |
