document.getElementById('get-video').addEventListener('click', function() {
    const timeInput = document.getElementById('meeting-time').value;
    
    if (!timeInput) {
        alert("Калі ласка, выберыце зручны час для прагляду");
        return;
    }

    // 1. Выбираем случайное видео
    const randomIndex = Math.floor(Math.random() * videoArchive.length);
    const video = videoArchive[randomIndex];

    // 2. Обработка даты для Google Calendar
    const dateSelected = new Date(timeInput);
    const startDate = dateSelected.toISOString().replace(/-|:|\.\d\d\d/g, "");
    
    // Конец события (делаем +1 час к началу)
    const endDateObj = new Date(dateSelected.getTime() + (60 * 60 * 1000));
    const endDate = endDateObj.toISOString().replace(/-|:|\.\d\d\d/g, "");

    // 3. Формируем URL для Google Календаря
    const calendarUrl = `https://www.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(video.title)}&dates=${startDate}/${endDate}&details=Посмотреть видео здесь: ${encodeURIComponent(video.url)}&sf=true&output=xml`;

    // 4. Предлагаем перейти
    const resultDiv = document.getElementById('result-link');
    resultDiv.innerHTML = `
        <p>Выбраны вам эпізод: <strong>${video.title}</strong></p>
        <a href="${calendarUrl}" target="_blank" class="btn-calendar">Дадаць у каляндар смартфона →</a>
    `;
});
