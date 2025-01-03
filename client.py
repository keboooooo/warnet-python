import socket
import json
import tkinter as tk
from tkinter import messagebox, ttk
import ctypes
import sys
import threading
import time
import os
import json

class WarnetClient:
    def __init__(self, server_host='localhost', server_port=5000):
        self.server_host = server_host
        self.server_port = server_port
        self.socket = None
        self.running = False
        self.last_server_ip = None  # Store last successful connection
        self.pc_type = None  # Add PC type
        
        # Config file path in Documents folder
        self.config_path = os.path.join(os.path.expanduser('~'), 'Documents', 'warnet_config.json')
        self.load_config()
        self.setup_gui()

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    self.server_host = config.get('server_ip', 'localhost')
                    self.last_server_ip = self.server_host
                    self.pc_type = config.get('pc_type', None)
                    return True
            return False
        except Exception as e:
            print(f"Error loading config: {e}")
            return False

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump({
                    'server_ip': self.server_host,
                    'pc_type': self.pc_type
                }, f)
        except Exception as e:
            print(f"Error saving config: {e}")
            
    def connect_to_server(self):
        try:
            # Create new socket if needed
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
                
            # Create and configure socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)  # 5 second timeout
            
            # Try to connect
            self.socket.connect((self.server_host, self.server_port))
            
            # Wait for server identification request
            server_request = self.socket.recv(1024).decode()
            if server_request == "IDENTIFY":
                # Get client network info
                hostname = socket.gethostname()
                try:
                    # Try to get real IP
                    client_ip = [ip for ip in socket.gethostbyname_ex(hostname)[2] 
                            if not ip.startswith('127.')][0]
                except:
                    # Fallback to basic hostname lookup
                    client_ip = socket.gethostbyname(hostname)
                
                # Send client info
                client_info = {
                    'client_ip': client_ip,
                    'hostname': hostname
                }
                self.socket.send(json.dumps(client_info).encode())
                
                # Store successful connection IP
                self.last_server_ip = self.server_host
                return True
            else:
                raise ConnectionError("Invalid server response")
                
        except socket.timeout:
            messagebox.showerror("Connection Error", 
                            "Connection timed out. Please check server address.")
            return False
        except ConnectionRefusedError:
            messagebox.showerror("Connection Error",
                            "Connection refused. Please check if server is running.")
            return False
        except Exception as e:
            messagebox.showerror("Connection Error", 
                            f"Cannot connect to server: {e}\nPlease check if server is running.")
            return False
        finally:
            if not self.socket:
                self.last_server_ip = None
    
    def disconnect_from_server(self):
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

    def setup_gui(self):
        self.window = tk.Tk()
        self.window.title('Warnet Client')
        self.window.geometry('300x200')
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Server settings frame
        self.settings_frame = tk.Frame(self.window)
        self.login_frame = tk.Frame(self.window)
        
        # Setup login frame
        tk.Label(self.login_frame, text="Username:").pack()
        self.username_entry = tk.Entry(self.login_frame)
        self.username_entry.pack()
        
        tk.Label(self.login_frame, text="Password:").pack()
        self.password_entry = tk.Entry(self.login_frame, show="*")
        self.password_entry.pack()
        
        tk.Button(self.login_frame, text="Login", command=self.login).pack(pady=10)

        # Show appropriate frame based on config
        if self.last_server_ip:
            if self.connect_to_server():
                self.login_frame.pack()
            else:
                self.show_ip_input()
        else:
            self.show_ip_input()

    def show_ip_input(self):
        tk.Label(self.settings_frame, text="Server IP:").pack()
        self.server_ip = tk.Entry(self.settings_frame)
        self.server_ip.insert(0, self.server_host)
        self.server_ip.pack()
        
        # Add PC type selection
        tk.Label(self.settings_frame, text="PC Type:").pack()
        self.pc_type_combo = ttk.Combobox(self.settings_frame, 
                                         values=['Normal', 'VIP', 'Gamer'],
                                         state='readonly')
        self.pc_type_combo.set('Normal')
        self.pc_type_combo.pack()
        
        tk.Button(self.settings_frame, text="Connect", 
                 command=self.connect_and_show_login).pack(pady=10)
        self.settings_frame.pack()

    def connect_and_show_login(self):
        self.server_host = self.server_ip.get()
        self.pc_type = self.pc_type_combo.get()
        if self.connect_to_server():
            self.save_config()  # Save successful IP
            self.settings_frame.pack_forget()
            self.login_frame.pack()

    def login(self):
        # Try to connect if not connected
        if not self.socket and self.last_server_ip:
            self.server_host = self.last_server_ip
            if not self.connect_to_server():
                return

        if not self.socket:
            messagebox.showerror("Error", "Not connected to server")
            return

        try:
            credentials = {
                'command': 'login',
                'username': self.username_entry.get(),
                'password': self.password_entry.get(),
                'pc_type': self.pc_type  # Add PC type to login request
            }
            self.socket.send(json.dumps(credentials).encode())
            response = json.loads(self.socket.recv(1024).decode())
            
            if response['status'] == 'success':
                self.running = True
                self.remaining_time = response['balance']
                
                # Hide title bar and move to top right
                self.window.overrideredirect(True)
                screen_width = self.window.winfo_screenwidth()
                window_width = 300
                window_height = 200
                self.window.geometry(f"{window_width}x{window_height}+{screen_width-window_width}+0")
                
                messagebox.showinfo("Success", "Login successful!")
                self.start_timer()
            else:
                messagebox.showerror("Error", response['message'])
                
        except Exception as e:
            messagebox.showerror("Error", f"Login failed: {str(e)}")
            self.disconnect_from_server()

    def start_timer(self):
        self.login_frame.pack_forget()
        self.timer_frame = tk.Frame(self.window)
        
        # Timer display
        self.timer_label = tk.Label(self.timer_frame, font=('Arial', 30))
        self.timer_label.pack(pady=10)
        
        # Stop button
        stop_button = ttk.Button(self.timer_frame, 
                                text="Stop Session", 
                                command=self.stop_session)
        stop_button.pack(pady=5)
        
        self.timer_frame.pack()
        
        # Convert hours to seconds for more precise counting
        self.remaining_seconds = int(self.remaining_time * 3600)
        
        def update_timer():
            if self.running and self.remaining_seconds > 0:
                hours = self.remaining_seconds // 3600
                minutes = (self.remaining_seconds % 3600) // 60
                seconds = self.remaining_seconds % 60
                
                time_string = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
                self.timer_label.config(text=time_string)
                
                self.remaining_seconds -= 1
                self.window.after(1000, update_timer)
            elif self.remaining_seconds <= 0:
                # Send stop session and reset GUI
                try:
                    stop_data = {
                        'command': 'stop_session',
                        'username': self.username_entry.get(),
                        'remaining_seconds': 0
                    }
                    self.socket.send(json.dumps(stop_data).encode())
                except:
                    pass
                
                # Reset GUI
                self.running = False
                self.window.overrideredirect(False)
                self.window.geometry('300x200')
                self.timer_frame.pack_forget()
                self.login_frame.pack()
                self.username_entry.delete(0, tk.END)
                self.password_entry.delete(0, tk.END)
                
                # Disconnect from server
                self.disconnect_from_server()
                messagebox.showinfo("Time's Up", "Your session has ended")
                self.lock_computer()

        update_timer()

    def stop_session(self):
        if messagebox.askyesno("Stop Session", "Are you sure you want to end your session?"):
            try:
                # Send stop session command to server
                stop_data = {
                    'command': 'stop_session',
                    'username': self.username_entry.get(),
                    'remaining_seconds': self.remaining_seconds
                }
                self.socket.send(json.dumps(stop_data).encode())
                
                # Restore title bar before closing
                self.window.overrideredirect(False)
                self.window.geometry('300x200')  # Reset window size
                
                # Disconnect from server
                self.disconnect_from_server()
                
                # Reset client state
                self.running = False
                self.timer_frame.pack_forget()
                self.login_frame.pack()
                self.username_entry.delete(0, tk.END)
                self.password_entry.delete(0, tk.END)
                self.lock_computer()
            except Exception as e:
                print(f"Error stopping session: {e}")

    def lock_computer(self):
        messagebox.showwarning("Time's Up", "Your session has ended!")
        ctypes.windll.user32.LockWorkStation()

    def on_closing(self):
        self.running = False
        if self.socket:
            self.socket.close()
        self.window.destroy()

    def run(self):
        self.window.mainloop()

if __name__ == '__main__':
    client = WarnetClient()
    client.run()