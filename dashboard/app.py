from flask import Flask, render_template, jsonify, request
import sqlite3
import os
import time
from datetime import datetime
import shutil

app = Flask(__name__)

# Path to the DHCP database
DB_PATH = '../dhcp.db'
DB_COPY_PATH = 'dhcp_copy.db'

def get_db_connection():
    # Create a copy of the database to work with
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, DB_COPY_PATH)
        # Ensure the copy has write permissions
        os.chmod(DB_COPY_PATH, 0o666)
    
    conn = sqlite3.connect(DB_COPY_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/leases')
def get_leases():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM leases')
    leases = cursor.fetchall()
    conn.close()
    
    # Convert to list of dictionaries
    lease_list = []
    for lease in leases:
        lease_dict = dict(lease)
        # Convert timestamps to readable format
        for key in ['lease_start', 'lease_end', 'last_seen']:
            if lease_dict[key]:
                lease_dict[key] = datetime.fromtimestamp(float(lease_dict[key])).strftime('%Y-%m-%d %H:%M:%S')
        lease_list.append(lease_dict)
    
    return jsonify(lease_list)

@app.route('/api/logs')
def get_logs():
    # Read the last 100 lines of the log file
    log_file = '../dhcp_server.log'
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
            return jsonify(lines[-100:])
    return jsonify([])

@app.route('/api/release', methods=['POST'])
def release_ip():
    mac_address = request.json.get('mac_address')
    if not mac_address:
        return jsonify({'error': 'MAC address is required'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Delete the lease from the database
        cursor.execute('DELETE FROM leases WHERE mac_address = ?', (mac_address,))
        conn.commit()
        
        # Try to copy the modified database back to the original location
        try:
            if os.path.exists(DB_COPY_PATH):
                shutil.copy2(DB_COPY_PATH, DB_PATH)
                # Ensure the original database has write permissions
                os.chmod(DB_PATH, 0o666)
                app.logger.info(f"Released IP for MAC {mac_address} in both databases")
                return jsonify({'success': True, 'message': f'Released IP for MAC {mac_address}'})
        except PermissionError:
            app.logger.warning(f"Could not update original database due to permission error. Lease released in copy database only.")
            return jsonify({
                'success': True, 
                'message': f'Released IP for MAC {mac_address} in copy database only',
                'warning': 'Could not update original database due to permission error'
            })
        except Exception as e:
            app.logger.error(f"Error updating original database: {str(e)}")
            return jsonify({
                'success': True, 
                'message': f'Released IP for MAC {mac_address} in copy database only',
                'warning': f'Error updating original database: {str(e)}'
            })
    except Exception as e:
        app.logger.error(f"Error releasing lease: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/status')
def get_status():
    # Check if the DHCP server is running by checking if the log file exists and has recent entries
    log_file = '../dhcp_server.log'
    if os.path.exists(log_file):
        # Check if the log file has been modified in the last 60 seconds
        if time.time() - os.path.getmtime(log_file) < 60:
            # Check if the log file contains the "Server initialized" message
            with open(log_file, 'r') as f:
                log_content = f.read()
                # Check for the initialization message in the last 100 lines
                last_lines = log_content.split('\n')[-100:]
                for line in last_lines:
                    if "Server initialized and ready to receive requests" in line:
                        return jsonify({'online': True})
    
    # Alternative method: check if the DHCP server process is running
    try:
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'dhcp_server.py'], 
                               capture_output=True, 
                               text=True, 
                               check=False)
        if result.returncode == 0 and result.stdout.strip():
            return jsonify({'online': True})
    except Exception as e:
        app.logger.error(f"Error checking DHCP server process: {str(e)}")
    
    return jsonify({'online': False})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5173) 