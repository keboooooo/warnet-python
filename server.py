import socket
import threading
import json
import sqlite3
from datetime import datetime, timedelta
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox
import random
import string

class WarnetAdmin:
    PC_CATEGORIES = {
        'Normal': {'rate': 3000, 'minutes': 60},
        'VIP': {'rate': 5000, 'minutes': 60},
        'Gamer': {'rate': 6000, 'minutes': 60}
    }

    def __init__(self, host='0.0.0.0', port=5000, gui_callback=None):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.clients = {}
        self.running = True
        self.gui_callback = gui_callback  # Callback to update GUI
        
        # Get server IP
        self.server_ip = self.get_local_ip()
        print(f"Server IP: {self.server_ip}")

        try:
            self.setup_database()
            print("Database initialized successfully")
        except Exception as e:
            print(f"Database error: {e}")
            sys.exit(1)

    def get_local_ip(self):
        try:
            # Get hostname and all associated IPs
            hostname = socket.gethostname()
            host_info = socket.gethostbyname_ex(hostname)
            
            # Filter out localhost (127.0.0.1)
            ip_list = [ip for ip in host_info[2] if not ip.startswith('127.')]
            
            # Return first non-localhost IP
            if ip_list:
                return ip_list[0]
            return '127.0.0.1'  # Fallback to localhost
        except Exception as e:
            print(f"Error getting local IP: {e}")
            return '127.0.0.1'

    def setup_database(self):
        self.conn = sqlite3.connect('warnet.db', check_same_thread=False)
        self.cur = self.conn.cursor()
        self.cur.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT,
                balance INTEGER DEFAULT 0,
                pc_type TEXT DEFAULT 'Normal'
            );
            CREATE TABLE IF NOT EXISTS sessions (
                client_ip TEXT,
                username TEXT,
                start_time TIMESTAMP,
                duration INTEGER,
                pc_type TEXT DEFAULT 'Normal'
            );
        ''')
        self.conn.commit()

    def start(self):
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"Server started on {self.host}:{self.port}")
            print("Waiting for clients...")
            
            while self.running:
                try:
                    client, address = self.server_socket.accept()
                    print(f"New connection from {address}")
                    client_thread = threading.Thread(target=self.handle_client, args=(client, address))
                    client_thread.daemon = True
                    client_thread.start()
                except Exception as e:
                    print(f"Error accepting client: {e}")

        except Exception as e:
            print(f"Server error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        print("\nShutting down server...")
        self.running = False
        self.conn.close()
        self.server_socket.close()

    def add_user(self, username, password):
        try:
            self.cur.execute('INSERT INTO users (username, password) VALUES (?, ?)', 
                           (username, password))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            print(f"Username {username} already exists")
            return False

    def convert_hours_to_minutes(self, hours, pc_type='Normal'):
        """Convert hours to minutes based on PC type"""
        return int(hours * self.PC_CATEGORIES[pc_type]['minutes'])

    def calculate_price(self, hours, pc_type='Normal'):
        """Calculate price based on hours and PC type"""
        return hours * self.PC_CATEGORIES[pc_type]['rate']

    def add_balance(self, username, hours, pc_type='Normal'):
        try:
            # Validate input
            if not isinstance(hours, (int, float)):
                raise ValueError("Hours must be a number")
            if hours <= 0:
                raise ValueError("Hours must be greater than 0")
            if pc_type not in self.PC_CATEGORIES:
                raise ValueError(f"Invalid PC type. Choose from: {', '.join(self.PC_CATEGORIES.keys())}")
                
            # Check if user exists
            self.cur.execute('SELECT username FROM users WHERE username = ?', (username,))
            user = self.cur.fetchone()
            
            if not user:
                raise ValueError(f"User '{username}' does not exist")
            
            # Convert hours to minutes for storage
            minutes = self.convert_hours_to_minutes(hours, pc_type)
            
            # Add balance
            self.cur.execute('''
                UPDATE users 
                SET balance = balance + ?, pc_type = ? 
                WHERE username = ?
            ''', (minutes, pc_type, username))
            self.conn.commit()
            return True
            
        except ValueError as ve:
            messagebox.showerror("Error", str(ve))
            return False
        except Exception as e:
            print(f"Add balance error: {e}")
            messagebox.showerror("Error", f"Failed to add balance: {str(e)}")
            self.conn.rollback()
            return False

    def list_users(self):
        self.cur.execute('SELECT username, balance FROM users')
        users = self.cur.fetchall()
        print("\nCurrent Users:")
        print("Username | Balance (minutes)")
        print("-" * 30)
        for user in users:
            print(f"{user[0]} | {user[1]}")

    def handle_client(self, client_socket, address):
        try:
            # Send identify request and get client info
            client_socket.send("IDENTIFY".encode())
            client_data = client_socket.recv(1024).decode()
            client_info = json.loads(client_data)
            
            session_start = None
            current_user = None
            pc_type = None
            
            self.clients[address] = {
                'socket': client_socket,
                'reported_ip': client_info.get('client_ip'),
                'hostname': client_info.get('hostname'),
                'connected_time': datetime.now(),
                'username': None,
                'session_start': None,
                'pc_type': None
            }

            while True:
                try:
                    data = client_socket.recv(1024).decode()
                    if not data:
                        break
                    
                    request = json.loads(data)
                    if request.get('command') == 'login':
                        response = self.verify_credentials(
                            request.get('username'),
                            request.get('password'),
                            request.get('pc_type')  # Include PC type in verification
                        )
                        if response['status'] == 'success':
                            current_user = request.get('username')
                            session_start = datetime.now()
                            self.clients[address]['username'] = current_user
                            self.clients[address]['session_start'] = session_start
                            self.clients[address]['pc_type'] = request.get('pc_type')
                            
                        client_socket.send(json.dumps(response).encode())
                    elif request.get('command') == 'stop_session':
                        if current_user:
                            session_end = datetime.now()
                            time_used = (session_end - session_start).total_seconds() / 3600
                            
                            # Update user balance
                            self.cur.execute('''
                                UPDATE users 
                                SET balance = balance - ? 
                                WHERE username = ?
                            ''', (int(time_used * 60), current_user))
                            
                            # Log session
                            self.cur.execute('''
                                INSERT INTO sessions (client_ip, username, start_time, duration, pc_type)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (client_info.get('client_ip'), current_user, session_start, 
                                int(time_used * 60), self.clients[address]['pc_type']))
                            
                            self.conn.commit()
                            client_socket.send(json.dumps({'status': 'success'}).encode())
                            break
                except Exception as e:
                    print(f"Error handling client request: {e}")
                    break

            # Client disconnected - Update balance
            if current_user and session_start:
                session_end = datetime.now()
                time_used = (session_end - session_start).total_seconds() / 3600
                
                # Update user balance
                self.cur.execute('''
                    UPDATE users 
                    SET balance = balance - ? 
                    WHERE username = ?
                ''', (int(time_used * 60), current_user))
                
                # Log session
                self.cur.execute('''
                    INSERT INTO sessions (client_ip, username, start_time, duration, pc_type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (client_info.get('client_ip'), current_user, session_start, 
                    int(time_used * 60), self.clients[address]['pc_type']))
                
                self.conn.commit()
                print(f"Updated balance for {current_user} - Used: {time_used:.2f} hours")
                
            self.remove_client(address)
                
        except Exception as e:
            print(f"Error handling client: {e}")
            self.remove_client(address)

    def remove_client(self, address):
        """Remove client and update GUI"""
        if address in self.clients:
            try:
                self.clients[address]['socket'].close()
            except:
                pass
            del self.clients[address]
            print(f"Client disconnected: {address}")
            
            # Update GUI if callback exists
            if self.gui_callback:
                self.gui_callback()

    def process_request(self, request, address):
        try:
            command = request.get('command')
            if command == 'login':
                print(f"Login request from {address}")
                return self.verify_credentials(
                    request.get('username'),
                    request.get('password'),
                    request.get('pc_type')  # Add pc_type parameter
                )
            elif command == 'stop_session':
                # Handle early session termination
                username = request.get('username')
                remaining_seconds = request.get('remaining_seconds')
                
                if username in self.clients[address]:
                    session_start = self.clients[address]['session_start']
                    session_end = datetime.now()
                    time_used = (session_end - session_start).total_seconds() / 3600
                    
                    # Update user balance
                    self.cur.execute('''
                        UPDATE users 
                        SET balance = balance - ? 
                        WHERE username = ?
                    ''', (int(time_used * 60), username))
                    
                    # Log session
                    self.cur.execute('''
                        INSERT INTO sessions (client_ip, username, start_time, duration, pc_type)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (self.clients[address]['reported_ip'], username, session_start, 
                        int(time_used * 60), self.clients[address]['pc_type']))
                    
                    self.conn.commit()
                    print(f"Updated balance for {username} - Used: {time_used:.2f} hours")
                
                return {'status': 'success'}
                
            return {'status': 'error', 'message': 'Invalid command'}
        except Exception as e:
            print(f"Process request error: {e}")
            return {'status': 'error', 'message': str(e)}

    def verify_credentials(self, username, password, pc_type):
        try:
            if not username or not password:
                return {'status': 'error', 'message': 'Username and password required'}

            # First check regular users
            self.cur.execute('''
                SELECT username, balance, pc_type
                FROM users 
                WHERE username = ? AND password = ?
            ''', (username, password))
            user = self.cur.fetchone()
            
            if user:
                if user[1] <= 0:  # Check balance
                    return {'status': 'error', 'message': 'No balance remaining'}
                
                if user[2] != pc_type:
                    return {'status': 'error', 'message': f'This account can only be used on {user[2]} PCs'}
                
                print(f"Regular user login: {username}")
                hours = user[1] / 60  # Convert minutes to hours
                return {'status': 'success', 'balance': hours}
            
            return {'status': 'error', 'message': 'Invalid credentials'}
            
        except Exception as e:
            print(f"Login verification error: {e}")
            return {'status': 'error', 'message': 'Login verification failed'}

    def handle_login(self, username, password):
        self.cur.execute('SELECT * FROM users WHERE username=? AND password=?',
                        (username, password))
        user = self.cur.fetchone()
        if user:
            return {'status': 'success', 'balance': user[2]}
        return {'status': 'error', 'message': 'Invalid credentials'}

    def delete_user(self, username):
        try:
            # Check if user exists
            self.cur.execute('SELECT username FROM users WHERE username = ?', (username,))
            user = self.cur.fetchone()
            
            if not user:
                raise ValueError(f"User '{username}' does not exist")
                
            # Delete user
            self.cur.execute('DELETE FROM users WHERE username = ?', (username,))
            self.conn.commit()
            return True
            
        except ValueError as ve:
            messagebox.showerror("Error", str(ve))
            return False
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete user: {str(e)}")
            self.conn.rollback()
            return False

class WarnetAdminGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Warnet Admin Server")
        
        # Dynamically set window size based on screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Use 80% of screen width and height
        window_width = int(screen_width * 0.8)
        window_height = int(screen_height * 0.8)
        
        # Center the window
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')
        
        # Configure root to expand
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        self.server = WarnetAdmin(gui_callback=self.update_clients_gui)
        self.setup_gui()
        
        # Start server in background
        self.server_thread = threading.Thread(target=self.server.start)
        self.server_thread.daemon = True
        self.server_thread.start()

    def update_clients_gui(self):
        """Safe method to update GUI from any thread"""
        self.root.after(0, self.refresh_clients)

    def setup_gui(self):
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        
        # Configure notebook to expand
        self.notebook.grid_rowconfigure(0, weight=1)
        self.notebook.grid_columnconfigure(0, weight=1)

        # Users tab
        self.users_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.users_frame, text="User Management")
        self.setup_users_tab()

        # Clients tab
        self.clients_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.clients_frame, text="Connected Clients")
        self.setup_clients_tab()

        # Server status (at the bottom, spanning full width)
        self.status_frame = ttk.Frame(self.root)
        self.status_frame.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        
        self.status_label = ttk.Label(self.status_frame, text="Server Status: Running", 
                                      relief='sunken', anchor='w')
        self.status_label.pack(fill='x', expand=True)

    def setup_users_tab(self):
        # Configure users frame to expand
        self.users_frame.grid_columnconfigure(0, weight=1)
        self.users_frame.grid_rowconfigure(1, weight=1)
        
        # Add User Frame
        add_frame = ttk.LabelFrame(self.users_frame, text="Add New User")
        add_frame.grid(row=0, column=0, sticky='ew', padx=5, pady=5)

        ttk.Label(add_frame, text="Username:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.username_entry = ttk.Entry(add_frame)
        self.username_entry.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        add_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(add_frame, text="Password:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.password_entry = ttk.Entry(add_frame, show="*")
        self.password_entry.grid(row=1, column=1, padx=5, pady=5, sticky='ew')

        ttk.Button(add_frame, text="Add User", command=self.add_user).grid(row=2, column=0, columnspan=2, pady=10)

        # Add Balance Frame
        balance_frame = ttk.LabelFrame(self.users_frame, text="Add Balance")
        balance_frame.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        balance_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(balance_frame, text="Username:").grid(row=0, column=0, padx=5, pady=5)
        self.balance_username = ttk.Entry(balance_frame)
        self.balance_username.grid(row=0, column=1, sticky='ew', padx=5)

        ttk.Label(balance_frame, text="Hours:").grid(row=1, column=0, padx=5, pady=5)
        self.balance_amount = ttk.Entry(balance_frame)
        self.balance_amount.grid(row=1, column=1, sticky='ew', padx=5)

        ttk.Label(balance_frame, text="PC Type:").grid(row=2, column=0, padx=5, pady=5)
        self.pc_type = ttk.Combobox(balance_frame, 
                                values=list(self.server.PC_CATEGORIES.keys()),
                                state='readonly')
        self.pc_type.set('Normal')
        self.pc_type.grid(row=2, column=1, sticky='ew', padx=5)

        # Add price display
        self.price_label = ttk.Label(balance_frame, text="Price: Rp 0")
        self.price_label.grid(row=3, column=0, columnspan=2, pady=5)

        def update_price(*args):
            try:
                hours = float(self.balance_amount.get() or 0)
                pc_type = self.pc_type.get()
                price = hours * self.server.PC_CATEGORIES[pc_type]['rate']
                self.price_label.config(text=f"Price: Rp {price:,.0f}")
            except ValueError:
                self.price_label.config(text="Price: Invalid input")

        self.balance_amount.bind('<KeyRelease>', update_price)
        self.pc_type.bind('<<ComboboxSelected>>', update_price)

        ttk.Button(balance_frame, text="Add Balance", 
                command=self.add_balance).grid(row=4, column=0, columnspan=2, pady=10)

        # Users List
        list_frame = ttk.LabelFrame(self.users_frame, text="User List")
        list_frame.grid(row=3, column=0, sticky='nsew', padx=5, pady=5)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        columns = ('Username', 'Password', 'Balance', 'PC Type')
        self.users_tree = ttk.Treeview(list_frame, columns=columns, show='headings')
        
        # Configure columns
        for col in columns:
            self.users_tree.heading(col, text=col)
            self.users_tree.column(col, width=100, anchor='center')
        
        self.users_tree.grid(row=0, column=0, sticky='nsew')

        # Scrollbars
        y_scroll = ttk.Scrollbar(list_frame, orient='vertical', 
                                command=self.users_tree.yview)
        x_scroll = ttk.Scrollbar(list_frame, orient='horizontal', 
                                command=self.users_tree.xview)
        
        y_scroll.grid(row=0, column=1, sticky='ns')
        x_scroll.grid(row=1, column=0, sticky='ew')
        
        self.users_tree.configure(yscroll=y_scroll.set, xscroll=x_scroll.set)

        # Buttons frame
        buttons_frame = ttk.Frame(list_frame)
        buttons_frame.grid(row=2, column=0, columnspan=2, pady=5)
        
        ttk.Button(buttons_frame, text="Refresh", 
                command=self.refresh_users).pack(side='left', padx=5)
        ttk.Button(buttons_frame, text="Delete User", 
                command=self.delete_selected_user).pack(side='left', padx=5)

        # Initial refresh
        self.refresh_users()

    def setup_clients_tab(self):
        # Configure clients frame to expand
        self.clients_frame.grid_columnconfigure(0, weight=1)
        self.clients_frame.grid_rowconfigure(0, weight=1)

        columns = ('IP', 'Username', 'Connected Since')
        self.clients_tree = ttk.Treeview(self.clients_frame, columns=columns, show='headings')
        for col in columns:
            self.clients_tree.heading(col, text=col)
            self.clients_tree.column(col, anchor='center')
        self.clients_tree.grid(row=0, column=0, sticky='nsew')

        # Scrollbar for Clients List
        clients_scrollbar = ttk.Scrollbar(self.clients_frame, orient='vertical', command=self.clients_tree.yview)
        clients_scrollbar.grid(row=0, column=1, sticky='ns')
        self.clients_tree.configure(yscroll=clients_scrollbar.set)

        ttk.Button(self.clients_frame, text="Refresh", command=self.refresh_clients).grid(row=1, column=0, columnspan=2, pady=5)

    def add_user(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        
        if username and password:
            if self.server.add_user(username, password):
                messagebox.showinfo("Success", f"User {username} added successfully")
                self.username_entry.delete(0, tk.END)
                self.password_entry.delete(0, tk.END)
                self.refresh_users()
            else:
                messagebox.showerror("Error", "Username already exists")
        else:
            messagebox.showerror("Error", "Please fill all fields")

    def add_balance(self):
        try:
            username = self.balance_username.get()
            hours = float(self.balance_amount.get())
            pc_type = self.pc_type.get()
            
            if self.server.add_balance(username, hours, pc_type):
                price = self.server.calculate_price(hours, pc_type)
                messagebox.showinfo("Success", 
                                  f"Added {hours} hours ({pc_type} PC)\nPrice: Rp {price:,.0f}")
                self.balance_username.delete(0, tk.END)
                self.balance_amount.delete(0, tk.END)
                self.pc_type.set('Normal')
                self.refresh_users()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid number of hours")

    def refresh_users(self):
        for item in self.users_tree.get_children():
            self.users_tree.delete(item)
        
        self.server.cur.execute('SELECT username, password, balance, pc_type FROM users')
        for user in self.server.cur.fetchall():
            hours = user[2] / 60  # Convert minutes to hours
            self.users_tree.insert('', tk.END, values=(
                user[0],          # username
                user[1],          # password
                f"{hours:.1f} hours",  # balance
                user[3]           # pc_type
            ))

    def refresh_clients(self):
        for item in self.clients_tree.get_children():
            self.clients_tree.delete(item)
        
        # Use client info from server's clients dictionary
        for address, client_info in self.server.clients.items():
            values = (
                client_info['reported_ip'],  # Use reported IP instead of socket IP
                client_info['hostname'],
                client_info['connected_time'].strftime('%Y-%m-%d %H:%M:%S')
            )
            self.clients_tree.insert('', tk.END, values=values)

    def delete_selected_user(self):
        # Get selected item
        selection = self.users_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a user to delete")
            return
            
        # Get username from selected item
        username = self.users_tree.item(selection[0])['values'][0]
        
        # Confirm deletion
        if messagebox.askyesno("Confirm Delete", 
                              f"Are you sure you want to delete user '{username}'?"):
            if self.server.delete_user(username):
                messagebox.showinfo("Success", f"User '{username}' deleted successfully")
                self.refresh_users()

    def run(self):
        self.refresh_users()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to shutdown the server?"):
            self.server.running = False
            self.root.destroy()
            sys.exit(0)

if __name__ == "__main__":
    admin_gui = WarnetAdminGUI()
    admin_gui.run()