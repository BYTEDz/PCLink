# Flutter Client - PCLink Discovery & Pairing Implementation

## Overview

This guide shows how to implement PCLink server discovery and pairing in your Flutter app. The process involves:

1. **Discovery**: Listen for UDP broadcasts from PCLink servers
2. **Pairing**: Send pairing request and handle user acceptance
3. **Connection**: Use the returned API key for authenticated requests

## 1. Dependencies

Add these to your `pubspec.yaml`:

```yaml
dependencies:
  http: ^1.1.0
  network_info_plus: ^4.0.0
  permission_handler: ^11.0.0
```

## 2. Discovery Implementation

### UDP Discovery Listener

```dart
import 'dart:io';
import 'dart:convert';
import 'dart:typed_data';

class PCLinkServer {
  final String hostname;
  final String ipAddress;
  final int port;
  final bool useHttps;
  
  PCLinkServer({
    required this.hostname,
    required this.ipAddress,
    required this.port,
    required this.useHttps,
  });
  
  String get protocol => useHttps ? 'https' : 'http';
  String get baseUrl => '$protocol://$ipAddress:$port';
}

class PCLinkDiscovery {
  static const int DISCOVERY_PORT = 38099;
  static const String BEACON_MAGIC = "PCLINK_DISCOVERY_BEACON_V1";
  
  RawDatagramSocket? _socket;
  bool _isListening = false;
  final List<PCLinkServer> _discoveredServers = [];
  
  // Callback for when servers are discovered
  Function(List<PCLinkServer>)? onServersUpdated;
  
  Future<void> startDiscovery() async {
    if (_isListening) return;
    
    try {
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, DISCOVERY_PORT);
      _socket!.broadcastEnabled = true;
      _isListening = true;
      
      print('Started listening for PCLink servers on port $DISCOVERY_PORT');
      
      _socket!.listen((RawSocketEvent event) {
        if (event == RawSocketEvent.read) {
          Datagram? datagram = _socket!.receive();
          if (datagram != null) {
            _handleDiscoveryPacket(datagram);
          }
        }
      });
      
    } catch (e) {
      print('Error starting discovery: $e');
    }
  }
  
  void _handleDiscoveryPacket(Datagram datagram) {
    try {
      String message = utf8.decode(datagram.data);
      Map<String, dynamic> payload = json.decode(message);
      
      // Verify this is a PCLink beacon
      if (payload['magic'] != BEACON_MAGIC) return;
      
      String serverIp = datagram.address.address;
      String hostname = payload['hostname'] ?? 'Unknown';
      int port = payload['port'] ?? 8000;
      bool useHttps = payload['https'] ?? true;
      
      // Check if we already know about this server
      bool exists = _discoveredServers.any((server) => 
          server.ipAddress == serverIp && server.port == port);
      
      if (!exists) {
        PCLinkServer server = PCLinkServer(
          hostname: hostname,
          ipAddress: serverIp,
          port: port,
          useHttps: useHttps,
        );
        
        _discoveredServers.add(server);
        print('Discovered PCLink server: $hostname at $serverIp:$port (HTTPS: $useHttps)');
        
        // Notify listeners
        onServersUpdated?.call(List.from(_discoveredServers));
      }
      
    } catch (e) {
      print('Error parsing discovery packet: $e');
    }
  }
  
  void stopDiscovery() {
    if (_socket != null) {
      _socket!.close();
      _socket = null;
    }
    _isListening = false;
    _discoveredServers.clear();
  }
  
  List<PCLinkServer> get discoveredServers => List.from(_discoveredServers);
}
```

## 3. Pairing Implementation

### Pairing Service

```dart
import 'package:http/http.dart' as http;

class PairingResult {
  final bool success;
  final String? apiKey;
  final String? certFingerprint;
  final String? error;
  
  PairingResult.success(this.apiKey, this.certFingerprint) 
      : success = true, error = null;
  
  PairingResult.error(this.error) 
      : success = false, apiKey = null, certFingerprint = null;
}

class PCLinkPairingService {
  
  Future<PairingResult> requestPairing(PCLinkServer server, String deviceName) async {
    try {
      String url = '${server.baseUrl}/pairing/request';
      
      Map<String, String> payload = {
        'device_name': deviceName,
      };
      
      print('Sending pairing request to: $url');
      print('Device name: $deviceName');
      
      http.Response response = await http.post(
        Uri.parse(url),
        headers: {
          'Content-Type': 'application/json',
        },
        body: json.encode(payload),
      ).timeout(Duration(seconds: 65)); // Server timeout is 60s + buffer
      
      print('Pairing response status: ${response.statusCode}');
      print('Pairing response body: ${response.body}');
      
      if (response.statusCode == 200) {
        Map<String, dynamic> responseData = json.decode(response.body);
        String apiKey = responseData['api_key'];
        String? certFingerprint = responseData['cert_fingerprint'];
        
        print('Pairing successful!');
        print('API Key: ${apiKey.substring(0, 8)}...');
        print('Cert Fingerprint: ${certFingerprint?.substring(0, 16) ?? 'None'}...');
        
        return PairingResult.success(apiKey, certFingerprint);
        
      } else if (response.statusCode == 403) {
        return PairingResult.error('Pairing request was denied by the user');
      } else if (response.statusCode == 408) {
        return PairingResult.error('Pairing request timed out - no user response');
      } else if (response.statusCode == 400) {
        return PairingResult.error('Invalid device name');
      } else {
        String errorMsg = 'Server error: ${response.statusCode}';
        try {
          Map<String, dynamic> errorData = json.decode(response.body);
          errorMsg = errorData['detail'] ?? errorMsg;
        } catch (e) {
          // Use default error message
        }
        return PairingResult.error(errorMsg);
      }
      
    } catch (e) {
      print('Pairing request failed: $e');
      if (e.toString().contains('TimeoutException')) {
        return PairingResult.error('Connection timeout - server may be unreachable');
      } else if (e.toString().contains('SocketException')) {
        return PairingResult.error('Network error - check your connection');
      } else {
        return PairingResult.error('Unexpected error: $e');
      }
    }
  }
  
  // Test connection with API key
  Future<bool> testConnection(PCLinkServer server, String apiKey) async {
    try {
      String url = '${server.baseUrl}/ping';
      
      http.Response response = await http.get(
        Uri.parse(url),
        headers: {
          'x-api-key': apiKey,
        },
      ).timeout(Duration(seconds: 10));
      
      return response.statusCode == 200;
    } catch (e) {
      print('Connection test failed: $e');
      return false;
    }
  }
}
```

## 4. UI Implementation

### Discovery & Pairing Screen

```dart
import 'package:flutter/material.dart';

class PCLinkPairingScreen extends StatefulWidget {
  @override
  _PCLinkPairingScreenState createState() => _PCLinkPairingScreenState();
}

class _PCLinkPairingScreenState extends State<PCLinkPairingScreen> {
  final PCLinkDiscovery _discovery = PCLinkDiscovery();
  final PCLinkPairingService _pairingService = PCLinkPairingService();
  
  List<PCLinkServer> _servers = [];
  bool _isDiscovering = false;
  bool _isPairing = false;
  String? _pairingStatus;
  
  @override
  void initState() {
    super.initState();
    _discovery.onServersUpdated = (servers) {
      setState(() {
        _servers = servers;
      });
    };
    _startDiscovery();
  }
  
  @override
  void dispose() {
    _discovery.stopDiscovery();
    super.dispose();
  }
  
  Future<void> _startDiscovery() async {
    setState(() {
      _isDiscovering = true;
      _pairingStatus = 'Searching for PCLink servers...';
    });
    
    await _discovery.startDiscovery();
    
    // Stop discovery after 30 seconds if no servers found
    Future.delayed(Duration(seconds: 30), () {
      if (_servers.isEmpty) {
        setState(() {
          _isDiscovering = false;
          _pairingStatus = 'No PCLink servers found. Make sure PCLink is running on your PC.';
        });
      }
    });
  }
  
  Future<void> _pairWithServer(PCLinkServer server) async {
    setState(() {
      _isPairing = true;
      _pairingStatus = 'Sending pairing request to ${server.hostname}...';
    });
    
    // Get device name (you might want to let user customize this)
    String deviceName = 'Flutter App'; // or get from device info
    
    PairingResult result = await _pairingService.requestPairing(server, deviceName);
    
    setState(() {
      _isPairing = false;
    });
    
    if (result.success) {
      // Save the API key and server info for future use
      await _saveConnectionInfo(server, result.apiKey!, result.certFingerprint);
      
      setState(() {
        _pairingStatus = 'Successfully paired with ${server.hostname}!';
      });
      
      // Navigate to main app or show success
      _showPairingSuccess(server, result.apiKey!);
      
    } else {
      setState(() {
        _pairingStatus = 'Pairing failed: ${result.error}';
      });
      
      _showPairingError(result.error!);
    }
  }
  
  Future<void> _saveConnectionInfo(PCLinkServer server, String apiKey, String? certFingerprint) async {
    // Save to SharedPreferences or secure storage
    // This is where you'd store the connection details for future use
    print('Saving connection info for ${server.hostname}');
  }
  
  void _showPairingSuccess(PCLinkServer server, String apiKey) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Pairing Successful!'),
        content: Text('Successfully connected to ${server.hostname}. You can now control your PC.'),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.of(context).pop();
              // Navigate to main app screen
            },
            child: Text('Continue'),
          ),
        ],
      ),
    );
  }
  
  void _showPairingError(String error) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Pairing Failed'),
        content: Text(error),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text('OK'),
          ),
        ],
      ),
    );
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Connect to PCLink'),
        actions: [
          IconButton(
            icon: Icon(Icons.refresh),
            onPressed: _isDiscovering ? null : () {
              _servers.clear();
              _startDiscovery();
            },
          ),
        ],
      ),
      body: Padding(
        padding: EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (_pairingStatus != null)
              Card(
                child: Padding(
                  padding: EdgeInsets.all(16),
                  child: Row(
                    children: [
                      if (_isDiscovering || _isPairing)
                        SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      SizedBox(width: 12),
                      Expanded(child: Text(_pairingStatus!)),
                    ],
                  ),
                ),
              ),
            
            SizedBox(height: 16),
            
            Text(
              'Available Servers:',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            
            SizedBox(height: 8),
            
            Expanded(
              child: _servers.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.computer, size: 64, color: Colors.grey),
                          SizedBox(height: 16),
                          Text(
                            'No servers found',
                            style: TextStyle(color: Colors.grey),
                          ),
                          SizedBox(height: 8),
                          Text(
                            'Make sure PCLink is running on your PC',
                            style: TextStyle(color: Colors.grey, fontSize: 12),
                          ),
                        ],
                      ),
                    )
                  : ListView.builder(
                      itemCount: _servers.length,
                      itemBuilder: (context, index) {
                        PCLinkServer server = _servers[index];
                        return Card(
                          child: ListTile(
                            leading: Icon(
                              Icons.computer,
                              color: server.useHttps ? Colors.green : Colors.orange,
                            ),
                            title: Text(server.hostname),
                            subtitle: Text(
                              '${server.ipAddress}:${server.port}\n${server.protocol.toUpperCase()}',
                            ),
                            trailing: ElevatedButton(
                              onPressed: _isPairing ? null : () => _pairWithServer(server),
                              child: Text('Connect'),
                            ),
                            isThreeLine: true,
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
```

## 5. Usage Example

### Main App Integration

```dart
void main() {
  runApp(MyApp());
}

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PCLink Client',
      home: PCLinkPairingScreen(),
    );
  }
}
```

## 6. Permissions (Android)

Add to `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
```

## 7. Testing Steps

1. **Start PCLink server** on your PC
2. **Run your Flutter app** on the same network
3. **Wait for discovery** - servers should appear automatically
4. **Tap "Connect"** on a server
5. **Accept the pairing request** on the PC (dialog will appear)
6. **Success!** - You'll get the API key for future requests

## 8. Error Handling

The implementation handles common errors:

- **Network timeouts**: Connection issues
- **User denial**: User clicks "No" on PC
- **Server errors**: Invalid requests or server issues
- **Discovery failures**: No servers found

## 9. Next Steps

After successful pairing:

1. **Save credentials** securely (SharedPreferences/Keychain)
2. **Use API key** for authenticated requests to PCLink endpoints
3. **Implement reconnection** logic for network changes
4. **Add manual server entry** option as fallback

This implementation provides a complete discovery and pairing system that matches PCLink's protocol and shows the acceptance dialog on the PC as requested.