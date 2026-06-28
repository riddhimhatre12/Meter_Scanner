class Config:
    SECRET_KEY = 'your_secret_key'
    SQLALCHEMY_DATABASE_URI = 'mysql://root:yourpassword@localhost/meter_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


### static/js/scripts.js (Frontend Interactions)
document.addEventListener("DOMContentLoaded", function () {
    let captureBtn = document.getElementById("capture-btn");
    if (captureBtn) {
        captureBtn.addEventListener("click", function () {
            alert("Capturing Image...");
        });
    }
});
