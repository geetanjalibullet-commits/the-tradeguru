import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import os

st.set_page_config(page_title="Enterprise Trading Manager", layout="wide")

# ==========================================
# DATABASE CONNECTION (SUPABASE / POSTGRESQL)
# ==========================================
# Get DB URL from Streamlit Secrets (Local) or Render Environment Variables
try:
    DATABASE_URL = st.secrets["DATABASE_URL"]
except:
    DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    st.error("DATABASE_URL not found! Please set it in secrets.toml or environment variables.")
    st.stop()

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def fetch_data(query, params=()):
    conn = get_db_connection()
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

# Initialize Tables for the first time
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_members (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            password TEXT DEFAULT '123456',
            role TEXT DEFAULT 'staff',
            manager_id INTEGER REFERENCES team_members(id) ON DELETE SET NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            team_member_id INTEGER REFERENCES team_members(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            phone_number TEXT,
            capital REAL DEFAULT 0.0,
            fee_type TEXT DEFAULT 'Profit Sharing',
            fee_value REAL DEFAULT 0.0,
            sub_duration TEXT DEFAULT 'NA'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
            index_name TEXT,
            strike REAL,
            option_type TEXT,
            quantity INTEGER,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            status TEXT DEFAULT 'open'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger (
            id SERIAL PRIMARY KEY,
            client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            transaction_type TEXT,
            amount REAL,
            capital_after REAL
        )
    ''')
    
    # Create the first Admin if table is empty
    cursor.execute("SELECT COUNT(*) as count FROM team_members")
    if cursor.fetchone()['count'] == 0:
        cursor.execute("INSERT INTO team_members (name, password, role) VALUES ('Admin', '123456', 'admin')")
        
    conn.commit()
    conn.close()

init_db()

# --- SESSION STATE INITIALIZATION ---
for key in ['form_reset', 'clear_tm_form', 'logged_in']:
    if key not in st.session_state: st.session_state[key] = False
for key in ['user_id', 'user_name', 'user_role']:
    if key not in st.session_state: st.session_state[key] = None

# ==========================================
# 1. LOGIN & REGISTRATION SCREEN
# ==========================================
if not st.session_state.logged_in:
    st.title("🔐 Enterprise Trading App - Secure Login")
    
    tab_login, tab_register = st.tabs(["Login", "Create New Account"])
    
    with tab_login:
        st.subheader("Team Member Login")
        login_name = st.text_input("Username (Your Name)")
        login_pass = st.text_input("Password", type="password")
        
        if st.button("Login", type="primary"):
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, name, role FROM team_members WHERE name = %s AND password = %s", (login_name, login_pass))
            user = cur.fetchone()
            conn.close()
            
            if user:
                st.session_state.logged_in = True
                st.session_state.user_id = user['id']
                st.session_state.user_name = user['name']
                st.session_state.user_role = user['role']
                st.success(f"Welcome {user['name']}! (Role: {user['role'].capitalize()})")
                st.rerun()
            else:
                st.error("Invalid Username or Password! Please try again.")
                
    with tab_register:
        st.subheader("Register a New Team Member")
        reg_name = st.text_input("New Username", key="reg_name")
        reg_pass = st.text_input("New Password", type="password", key="reg_pass")
        
        if st.button("Create Account"):
            if reg_name and reg_pass:
                try:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO team_members (name, password, role) VALUES (%s, %s, 'staff')", (reg_name, reg_pass))
                    conn.commit()
                    conn.close()
                    st.success(f"Account created for {reg_name}! You can now log in.")
                except psycopg2.IntegrityError:
                    st.error("This username already exists. Please choose a different name.")
            else:
                st.warning("Both Username and Password are required.")

# ==========================================
# 2. MAIN DASHBOARD (Only visible after login)
# ==========================================
else:
    team_member_id = st.session_state.user_id
    selected_member = st.session_state.user_name
    role = st.session_state.user_role
    is_admin = (role == 'admin')
    is_leader = (role == 'leader')

    # --- SIDEBAR ---
    st.sidebar.title("👤 My Profile")
    st.sidebar.success(f"Logged in as: {selected_member}")
    if is_admin: st.sidebar.info("👑 Role: Administrator")
    elif is_leader: st.sidebar.info("👨‍💼 Role: Team Leader")
    else: st.sidebar.info("👤 Role: Staff Member")
        
    if is_admin or is_leader:
        with st.sidebar.expander("➕ Add Team Member"):
            default_tm_name = "" if st.session_state.clear_tm_form else st.session_state.get('new_tm_input', '')
            default_tm_pass = "123456" if st.session_state.clear_tm_form else st.session_state.get('new_tm_pass', '123456')
            if st.session_state.clear_tm_form: st.session_state.clear_tm_form = False
            
            with st.form("add_tm_form", clear_on_submit=True):
                new_tm_name = st.text_input("Member Name", value=default_tm_name, key="new_tm_input")
                new_tm_pass = st.text_input("Password", value=default_tm_pass, key="new_tm_pass")
                new_tm_role = st.selectbox("Assign Role", ["staff", "leader", "admin"]) if is_admin else "staff"
                
                if st.form_submit_button("Create Member"):
                    if new_tm_name:
                        try:
                            conn = get_db_connection()
                            cur = conn.cursor()
                            mgr_id = team_member_id if is_leader else None
                            cur.execute("INSERT INTO team_members (name, password, role, manager_id) VALUES (%s, %s, %s, %s)", 
                                         (new_tm_name, new_tm_pass, new_tm_role, mgr_id))
                            conn.commit()
                            conn.close()
                            st.session_state.clear_tm_form = True 
                            st.success(f"Member '{new_tm_name}' added successfully!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            st.error("This member name already exists!")
                    else:
                        st.error("Member Name is required!")
                    
    if st.sidebar.button("🚪 Logout"):
        st.session_state.logged_in = False
        for k in ['user_id', 'user_name', 'user_role']: st.session_state[k] = None
        st.rerun()

    st.title(f"📊 Dashboard - {selected_member}")
    
    if is_admin or is_leader:
        tab_team, tab1, tab2, tab3, tab4, tab5 = st.tabs(["🧑‍💼 Manage Team", "👥 Client List", "➕ Add New Client", "📈 Manage Trades", "📖 View Ledger", "📊 Reports & PDF"])
    else:
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["👥 Client List", "➕ Add New Client", "📈 Manage Trades", "📖 View Ledger", "📊 Reports & PDF"])    
    
    # --- TAB: MANAGE TEAM ---
    if is_admin or is_leader:
        with tab_team:
            st.subheader("👥 Team Management")
            if is_admin:
                team_df = fetch_data('''SELECT t1.id, t1.name, t1.role, t1.password, t2.name as managed_by 
                                        FROM team_members t1 LEFT JOIN team_members t2 ON t1.manager_id = t2.id''')
                st.dataframe(team_df, use_container_width=True, hide_index=True)
                st.divider()
                c1, c2, c3 = st.columns(3)
                
                with c1:
                    st.write("### 🔑 Reset Password")
                    tm_sel = st.selectbox("Select Member", team_df['id'].astype(str) + " - " + team_df['name'], key="adm_pass_box")
                    new_pass = st.text_input("New Password", key="adm_new_pass")
                    if st.button("Update Password", key="adm_btn_pass"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("UPDATE team_members SET password = %s WHERE id = %s", (new_pass, int(tm_sel.split(" - ")[0])))
                        conn.commit()
                        conn.close()
                        st.success("Password Updated!")
                        st.rerun()
                        
                with c2:
                    st.write("### 🔄 Assign Manager / Role")
                    tm_assign = st.selectbox("Select Member", team_df['id'].astype(str) + " - " + team_df['name'], key="adm_assign_box")
                    new_role = st.selectbox("Change Role", ["staff", "leader", "admin"])
                    leaders_df = fetch_data("SELECT id, name FROM team_members WHERE role IN ('admin', 'leader')")
                    lead_options = ["None"] + (leaders_df['id'].astype(str) + " - " + leaders_df['name']).tolist()
                    new_mgr = st.selectbox("Assign to Team Leader", lead_options)
                    
                    if st.button("Update Role/Manager"):
                        m_id = None if new_mgr == "None" else int(new_mgr.split(" - ")[0])
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("UPDATE team_members SET role = %s, manager_id = %s WHERE id = %s", (new_role, m_id, int(tm_assign.split(" - ")[0])))
                        conn.commit()
                        conn.close()
                        st.success("Role and Manager Updated!")
                        st.rerun()

                with c3:
                    st.write("### ❌ Delete Member")
                    del_tm_sel = st.selectbox("Select Member to Delete", team_df['id'].astype(str) + " - " + team_df['name'], key="adm_del_box")
                    if st.button("Delete User", type="primary"):
                        tm_id_del = int(del_tm_sel.split(" - ")[0])
                        if tm_id_del == team_member_id:
                            st.error("Cannot delete your own account!")
                        else:
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("DELETE FROM team_members WHERE id = %s", (tm_id_del,))
                            conn.commit()
                            conn.close()
                            st.success("Member deleted successfully!")
                            st.rerun()

            elif is_leader:
                team_df = fetch_data("SELECT id, name, role, password FROM team_members WHERE manager_id = %s", (team_member_id,))
                if not team_df.empty:
                    st.dataframe(team_df, use_container_width=True, hide_index=True)
                    st.divider()
                    c1, c2 = st.columns(2)
                    with c1:
                        st.write("### 🔑 Reset Staff Password")
                        tm_sel = st.selectbox("Select Staff", team_df['id'].astype(str) + " - " + team_df['name'])
                        new_pass = st.text_input("New Password")
                        if st.button("Update Password"):
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("UPDATE team_members SET password = %s WHERE id = %s", (new_pass, int(tm_sel.split(" - ")[0])))
                            conn.commit()
                            conn.close()
                            st.success("Password Updated!")
                            st.rerun()
                    with c2:
                        st.write("### ❌ Delete Staff Member")
                        del_tm_sel = st.selectbox("Select Staff to Delete", team_df['id'].astype(str) + " - " + team_df['name'])
                        if st.button("Delete Staff", type="primary"):
                            tm_id_del = int(del_tm_sel.split(" - ")[0])
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("DELETE FROM team_members WHERE id = %s", (tm_id_del,))
                            conn.commit()
                            conn.close()
                            st.success("Staff deleted successfully!")
                            st.rerun()
                else:
                    st.info("You have no staff assigned to you yet.")

    # --- TAB 1: CLIENT LIST ---
    with tab1:
        st.subheader("Client List")
        if is_admin:
            clients_df = fetch_data('''SELECT c.id, c.name, c.phone_number, c.capital, c.fee_type, c.fee_value, tm.name as managed_by 
                                       FROM clients c JOIN team_members tm ON c.team_member_id = tm.id''')
        elif is_leader:
            clients_df = fetch_data('''SELECT c.id, c.name, c.phone_number, c.capital, c.fee_type, c.fee_value, tm.name as managed_by 
                                       FROM clients c JOIN team_members tm ON c.team_member_id = tm.id
                                       WHERE tm.id = %s OR tm.manager_id = %s''', (team_member_id, team_member_id))
        else:
            clients_df = fetch_data("SELECT id, name, phone_number, capital, fee_type, fee_value, 'Self' as managed_by FROM clients WHERE team_member_id = %s", (team_member_id,))
        
        if not clients_df.empty:
            st.dataframe(clients_df, use_container_width=True, hide_index=True)
            
            if is_admin or is_leader:
                st.divider()
                st.write("### ⚙️ Manager Controls: Edit or Delete Client")
                col1, col2 = st.columns(2)
                
                with col1:
                    del_client_id = st.selectbox("Select Client to Delete", clients_df['id'].astype(str) + " - " + clients_df['name'], key="del_box")
                    if st.button("❌ Delete Client"):
                        c_id = int(del_client_id.split(" - ")[0])
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute('DELETE FROM clients WHERE id = %s', (c_id,))
                        conn.commit()
                        conn.close()
                        st.success("Client deleted successfully!")
                        st.rerun()
                
                with col2:
                    edit_client_id = st.selectbox("Select Client to Edit", clients_df['id'].astype(str) + " - " + clients_df['name'], key="edit_box")
                    c_id_edit = int(edit_client_id.split(" - ")[0])
                    curr_data = clients_df[clients_df['id'] == c_id_edit].iloc[0]
                    
                    new_name = st.text_input("Edit Name", value=curr_data['name'])
                    new_phone = st.text_input("Edit Phone", value=curr_data['phone_number'])
                    if st.button("✏️ Update Client Info"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute('UPDATE clients SET name = %s, phone_number = %s WHERE id = %s', (new_name, new_phone, c_id_edit))
                        conn.commit()
                        conn.close()
                        st.success("Client info updated!")
                        st.rerun()
            else:
                st.info("🔒 Edit and Delete controls are restricted to Admins and Team Leaders.")
        else:
            st.write("No clients found.")

    # --- TAB 2: ADD NEW CLIENT ---
    with tab2:
        st.subheader("Add a New Client")
        default_name = "" if st.session_state.form_reset else st.session_state.get('c_name_input', '')
        default_phone = "" if st.session_state.form_reset else st.session_state.get('c_phone_input', '')
        default_cap = 0.0 if st.session_state.form_reset else st.session_state.get('c_cap_input', 0.0)
        
        if st.session_state.form_reset: st.session_state.form_reset = False
            
        with st.form("add_client_form", clear_on_submit=True):
            c_name = st.text_input("Client Name", value=default_name, key="c_name_input")
            c_phone = st.text_input("Phone Number", value=default_phone, key="c_phone_input")
            c_capital = st.number_input("Initial Capital", min_value=0.0, step=1000.0, value=default_cap, key="c_cap_input")
            
            fee_type = st.selectbox("Working Model", ["Profit Sharing", "Subscription"])
            profit_share = st.number_input("Profit Share Percentage (%)", min_value=0.0, max_value=100.0, step=1.0)
            sub_duration = st.selectbox("Subscription Plan", ["NA", "Monthly", "Quarterly", "Half-Yearly", "Yearly"])
            sub_amount = st.number_input("Subscription Amount (₹)", min_value=0.0, step=500.0)
            
            if st.form_submit_button("Save Client") and c_name:
                final_fee_value = profit_share if fee_type == "Profit Sharing" else sub_amount
                final_sub_duration = "NA" if fee_type == "Profit Sharing" else (sub_duration if sub_duration != "NA" else "Monthly")

                conn = get_db_connection()
                cursor = conn.cursor()
                # RETURNING id in Postgres to get the inserted client ID
                cursor.execute('''INSERT INTO clients (team_member_id, name, phone_number, capital, fee_type, fee_value, sub_duration) 
                                  VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''', 
                               (team_member_id, c_name, c_phone, c_capital, fee_type, final_fee_value, final_sub_duration))
                client_id = cursor.fetchone()['id']
                
                cursor.execute('INSERT INTO ledger (client_id, description, transaction_type, amount, capital_after) VALUES (%s, %s, %s, %s, %s)',
                               (client_id, 'Initial Deposit', 'deposit', c_capital, c_capital))
                conn.commit()
                conn.close()
                st.session_state.form_reset = True 
                st.success(f"Client '{c_name}' added successfully!")
                st.rerun()

    # --- TAB 3: MANAGE TRADES ---
    with tab3:
        st.subheader("Manage Client Trades")
        if not clients_df.empty:
            col1, col2 = st.columns(2)
            with col1:
                st.write("### 🟢 Open a New Trade")
                client_sel = st.selectbox("Select Client", clients_df['id'].astype(str) + " - " + clients_df['name'])
                category = st.selectbox("Segment", ["Index", "Equity"])
                
                stock_list = sorted(['360ONE', 'ABB', 'ADANIENT', 'HDFCBANK', 'RELIANCE', 'TCS', 'INFY', 'SBI'])
                
                if category == "Index":
                    inst_type = st.selectbox("Instrument Type", ["Futures", "Options"])
                    instrument_name = st.selectbox("Index Name", ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"])
                else:
                    inst_type = st.selectbox("Instrument Type", ["Cash", "Futures", "Options"])
                    instrument_name = st.selectbox("Stock Name", stock_list)

                if inst_type == "Options":
                    c_s1, c_s2 = st.columns(2)
                    with c_s1: t_strike = st.number_input("Strike Price", min_value=0.0, step=0.5)
                    with c_s2: t_type = st.selectbox("Option Type", ["CE", "PE"])
                else:
                    t_strike = 0.0; t_type = "NA"
                
                c_q1, c_q2 = st.columns(2)
                with c_q1: t_qty = st.number_input("Total Quantity", min_value=1, step=1)
                with c_q2: t_entry = st.number_input("Entry Price (Avg)", min_value=0.0, step=0.5)
                
                if st.button("Open Trade", type="primary"):
                    c_id = int(client_sel.split(" - ")[0])
                    full_instrument = f"{instrument_name} ({inst_type})"
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO trades (client_id, index_name, strike, option_type, quantity, entry_price, status) VALUES (%s, %s, %s, %s, %s, %s, 'open')", 
                                 (c_id, full_instrument, t_strike, t_type, t_qty, t_entry))
                    conn.commit()
                    conn.close()
                    st.success("Trade Opened Successfully!")
                    st.rerun()

            with col2:
                st.write("### 🔴 Close Open Trades")
                if is_admin:
                    open_trades = fetch_data('''SELECT t.id, c.name as client_name, t.index_name, t.strike, t.option_type, t.quantity, t.entry_price, t.client_id 
                                                FROM trades t JOIN clients c ON t.client_id = c.id WHERE t.status = 'open' ''')
                elif is_leader:
                    open_trades = fetch_data('''SELECT t.id, c.name as client_name, t.index_name, t.strike, t.option_type, t.quantity, t.entry_price, t.client_id 
                                                FROM trades t JOIN clients c ON t.client_id = c.id JOIN team_members tm ON c.team_member_id = tm.id
                                                WHERE (tm.id = %s OR tm.manager_id = %s) AND t.status = 'open' ''', (team_member_id, team_member_id))
                else:
                    open_trades = fetch_data('''SELECT t.id, c.name as client_name, t.index_name, t.strike, t.option_type, t.quantity, t.entry_price, t.client_id 
                                                FROM trades t JOIN clients c ON t.client_id = c.id WHERE c.team_member_id = %s AND t.status = 'open' ''', (team_member_id,))
                
                if not open_trades.empty:
                    with st.form("close_trade_form", clear_on_submit=True):
                        trade_options = []
                        for _, row in open_trades.iterrows():
                            lbl = f"{row['id']} - {row['client_name']} [{row['index_name']} | Qty: {row['quantity']}]" if row['option_type'] == "NA" else f"{row['id']} - {row['client_name']} [{row['index_name']} {row['strike']} {row['option_type']} | Qty: {row['quantity']}]"
                            trade_options.append(lbl)
                            
                        trade_sel = st.selectbox("Select Open Trade to Close", trade_options)
                        t_exit = st.number_input("Exit Price (Avg Sell Price)", min_value=0.0, step=0.5)
                        
                        if st.form_submit_button("Close Trade & Update PNL"):
                            trade_id = int(trade_sel.split(" - ")[0])
                            trade_row = open_trades[open_trades['id'] == trade_id].iloc[0]
                            c_id = int(trade_row['client_id'])
                            pnl = (t_exit - float(trade_row['entry_price'])) * int(trade_row['quantity'])
                            
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE trades SET exit_price = %s, pnl = %s, status = 'closed' WHERE id = %s", (t_exit, pnl, trade_id))
                            
                            cursor.execute("SELECT capital FROM clients WHERE id = %s", (c_id,))
                            client_data = cursor.fetchone()
                            new_capital = client_data['capital'] + pnl
                            cursor.execute("UPDATE clients SET capital = %s WHERE id = %s", (new_capital, c_id))
                            
                            desc = f"Trade Result: {trade_row['index_name']}" if trade_row['option_type'] == "NA" else f"Trade Result: {trade_row['index_name']} {trade_row['strike']} {trade_row['option_type']}"
                            cursor.execute("INSERT INTO ledger (client_id, description, transaction_type, amount, capital_after) VALUES (%s, %s, 'trade_pnl', %s, %s)", (c_id, desc, pnl, new_capital))
                            conn.commit()
                            conn.close()
                            
                            if pnl >= 0: st.success(f"Trade Closed! Profit: ₹{pnl:.2f}. Capital Updated.")
                            else: st.error(f"Trade Closed! Loss: ₹{pnl:.2f}. Capital Updated.")
                            st.rerun()
                else:
                    st.info("No open trades right now.")
        else:
            st.warning("Please add a client before opening trades.")

    # --- TAB 4: CLIENT LEDGER ---
    with tab4:
        st.subheader("Check Client Ledger")
        if not clients_df.empty:
            selected_client_id = st.selectbox("Select Client", clients_df['id'].astype(str) + " - " + clients_df['name'], key="ledger_select_client")
            c_id = int(selected_client_id.split(" - ")[0])
            
            ledger_df = fetch_data("SELECT timestamp, description, transaction_type, amount, capital_after FROM ledger WHERE client_id = %s ORDER BY timestamp DESC", (c_id,))
            st.dataframe(ledger_df, use_container_width=True, hide_index=True)

            st.write("### Client's Trade History")
            trades_df = fetch_data("SELECT index_name, strike, option_type, quantity, entry_price, exit_price, pnl, status FROM trades WHERE client_id = %s ORDER BY id DESC", (c_id,))
            st.dataframe(trades_df, use_container_width=True, hide_index=True)
    
        # --- TAB 5: REPORTS & PDF DOWNLOAD ---
    with tab5:
        st.subheader("📅 Date-wise Performance & Fee Report")
        if is_admin: st.info("👑 Administrator: Viewing full company reports.")
        elif is_leader: st.info("👨‍💼 Team Leader: Viewing your team's reports.")
            
        col1, col2 = st.columns(2)
        with col1: start_date = st.date_input("Start Date", pd.to_datetime("today") - pd.Timedelta(days=30))
        with col2: end_date = st.date_input("End Date", pd.to_datetime("today"))
            
        if st.button("Generate & View Report", type="primary"):
            # --------------------------
            # 1. TEAM QUERY (For PDF 1st section)
            # --------------------------
            if is_admin:
                team_query = '''SELECT tm.name as Team_Member, tm.role as Role, COUNT(l.id) as Total_Trades, SUM(l.amount) as Total_PNL 
                                FROM ledger l JOIN clients c ON l.client_id = c.id JOIN team_members tm ON c.team_member_id = tm.id 
                                WHERE l.transaction_type = 'trade_pnl' AND DATE(l.timestamp) >= %s AND DATE(l.timestamp) <= %s GROUP BY tm.name, tm.role'''
                team_df = fetch_data(team_query, (str(start_date), str(end_date)))
            elif is_leader:
                team_query = '''SELECT tm.name as Team_Member, tm.role as Role, COUNT(l.id) as Total_Trades, SUM(l.amount) as Total_PNL 
                                FROM ledger l JOIN clients c ON l.client_id = c.id JOIN team_members tm ON c.team_member_id = tm.id 
                                WHERE (tm.id = %s OR tm.manager_id = %s) AND l.transaction_type = 'trade_pnl' AND DATE(l.timestamp) >= %s AND DATE(l.timestamp) <= %s GROUP BY tm.name, tm.role'''
                team_df = fetch_data(team_query, (team_member_id, team_member_id, str(start_date), str(end_date)))
            else:
                team_df = pd.DataFrame()

            if not team_df.empty:
                st.write("### 🏆 Overall Team Performance")
                st.dataframe(team_df, use_container_width=True, hide_index=True)

            # --------------------------
            # 2. CLIENT QUERY (For App Display & PDF 2nd Section)
            # --------------------------
            if is_admin:
                client_query = '''SELECT tm.name as Team_Member, c.name as Client_Name, c.fee_type, c.fee_value, c.sub_duration, COUNT(l.id) as Total_Trades, SUM(l.amount) as Total_PNL 
                                  FROM ledger l JOIN clients c ON l.client_id = c.id JOIN team_members tm ON c.team_member_id = tm.id 
                                  WHERE l.transaction_type = 'trade_pnl' AND DATE(l.timestamp) >= %s AND DATE(l.timestamp) <= %s GROUP BY tm.name, c.name, c.fee_type, c.fee_value, c.sub_duration'''
                client_df = fetch_data(client_query, (str(start_date), str(end_date)))
            elif is_leader:
                client_query = '''SELECT tm.name as Team_Member, c.name as Client_Name, c.fee_type, c.fee_value, c.sub_duration, COUNT(l.id) as Total_Trades, SUM(l.amount) as Total_PNL 
                                  FROM ledger l JOIN clients c ON l.client_id = c.id JOIN team_members tm ON c.team_member_id = tm.id 
                                  WHERE (tm.id = %s OR tm.manager_id = %s) AND l.transaction_type = 'trade_pnl' AND DATE(l.timestamp) >= %s AND DATE(l.timestamp) <= %s GROUP BY tm.name, c.name, c.fee_type, c.fee_value, c.sub_duration'''
                client_df = fetch_data(client_query, (team_member_id, team_member_id, str(start_date), str(end_date)))
            else:
                client_query = '''SELECT c.name as Client_Name, c.fee_type, c.fee_value, c.sub_duration, COUNT(l.id) as Total_Trades, SUM(l.amount) as Total_PNL 
                                  FROM ledger l JOIN clients c ON l.client_id = c.id 
                                  WHERE l.transaction_type = 'trade_pnl' AND c.team_member_id = %s AND DATE(l.timestamp) >= %s AND DATE(l.timestamp) <= %s GROUP BY c.name, c.fee_type, c.fee_value, c.sub_duration'''
                client_df = fetch_data(client_query, (team_member_id, str(start_date), str(end_date)))
            
            # CALCULATE FEES
            if not client_df.empty:
                client_df['My_Fee_(Rs)'] = client_df.apply(lambda r: (r['Total_PNL'] * (r['fee_value'] / 100)) if r['fee_type'] == 'Profit Sharing' and r['Total_PNL'] > 0 else (r['fee_value'] if r['fee_type'] != 'Profit Sharing' else 0.0), axis=1)
                client_df['Plan_Details'] = client_df.apply(lambda r: f"Profit Share ({r['fee_value']}%)" if r['fee_type'] == 'Profit Sharing' else f"Sub ({r['sub_duration']})", axis=1)
                
                if is_admin or is_leader:
                    display_df = client_df[['Team_Member', 'Client_Name', 'Total_Trades', 'Total_PNL', 'Plan_Details', 'My_Fee_(Rs)']]
                else:
                    display_df = client_df[['Client_Name', 'Total_Trades', 'Total_PNL', 'Plan_Details', 'My_Fee_(Rs)']]
                
                st.write("### 👤 Client Performance & Fees")
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No client trades found in this date range.")
                
            # --------------------------
            # 3. PDF GENERATION LOGIC
            # --------------------------
            if not team_df.empty or not client_df.empty:
                from fpdf import FPDF
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", 'B', 16)
                pdf.cell(200, 10, "Trading Performance & Fee Report", ln=True, align='C')
                pdf.set_font("Arial", '', 12)
                pdf.cell(200, 10, f"Period: {start_date} to {end_date}", ln=True, align='C')
                pdf.ln(10)
                
                if not team_df.empty:
                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(200, 10, "1. Overall Team Performance", ln=True)
                    pdf.set_font("Arial", 'B', 11)
                    pdf.cell(50, 10, "Team Member", border=1)
                    pdf.cell(30, 10, "Role", border=1)
                    pdf.cell(30, 10, "Trades", border=1)
                    pdf.cell(40, 10, "Total PNL (Rs)", border=1, ln=True)
                    
                    pdf.set_font("Arial", '', 11)
                    for _, row in team_df.iterrows():
                        pdf.cell(50, 10, str(row['Team_Member'])[:18], border=1)
                        pdf.cell(30, 10, str(row['Role']).capitalize(), border=1)
                        pdf.cell(30, 10, str(row['Total_Trades']), border=1)
                        pdf.cell(40, 10, f"{row['Total_PNL'] if pd.notnull(row['Total_PNL']) else 0:.2f}", border=1, ln=True)
                    pdf.ln(10)
                
                if not client_df.empty:
                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(200, 10, f"2. Client Performance & Fee Details", ln=True)
                    pdf.set_font("Arial", 'B', 10)
                    
                    if is_admin or is_leader:
                        pdf.cell(35, 10, "Manager", border=1)
                        pdf.cell(40, 10, "Client Name", border=1)
                        pdf.cell(20, 10, "Trades", border=1)
                        pdf.cell(25, 10, "Total PNL", border=1)
                        pdf.cell(40, 10, "Plan", border=1)
                        pdf.cell(30, 10, "Fee (Rs)", border=1, ln=True)
                        
                        pdf.set_font("Arial", '', 10)
                        for _, row in display_df.iterrows():
                            pdf.cell(35, 10, str(row['Team_Member'])[:15], border=1)
                            pdf.cell(40, 10, str(row['Client_Name'])[:15], border=1)
                            pdf.cell(20, 10, str(row['Total_Trades']), border=1)
                            pdf.cell(25, 10, f"{row['Total_PNL'] if pd.notnull(row['Total_PNL']) else 0:.2f}", border=1)
                            pdf.cell(40, 10, str(row['Plan_Details'])[:18], border=1)
                            pdf.cell(30, 10, f"{row['My_Fee_(Rs)']:.2f}", border=1, ln=True)
                    else:
                        pdf.cell(45, 10, "Client Name", border=1)
                        pdf.cell(25, 10, "Trades", border=1)
                        pdf.cell(30, 10, "Total PNL", border=1)
                        pdf.cell(50, 10, "Plan Details", border=1)
                        pdf.cell(35, 10, "My Fee (Rs)", border=1, ln=True)
                        
                        pdf.set_font("Arial", '', 10)
                        for _, row in display_df.iterrows():
                            pdf.cell(45, 10, str(row['Client_Name'])[:20], border=1)
                            pdf.cell(25, 10, str(row['Total_Trades']), border=1)
                            pdf.cell(30, 10, f"{row['Total_PNL'] if pd.notnull(row['Total_PNL']) else 0:.2f}", border=1)
                            pdf.cell(50, 10, str(row['Plan_Details'])[:22], border=1)
                            pdf.cell(35, 10, f"{row['My_Fee_(Rs)']:.2f}", border=1, ln=True)
                
                pdf_file_name = "Trading_Fee_Report.pdf"
                pdf.output(pdf_file_name)
                
                with open(pdf_file_name, "rb") as f:
                    pdf_bytes = f.read()
                    
                st.download_button(
                    label="⬇️ Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"Fee_Report_{start_date}_to_{end_date}.pdf",
                    mime="application/pdf"
                )