// This file can be used for additional JavaScript functionality
// Most of the core functionality is already included in the index.html file

// Example of a utility function that could be added:
function formatTimestamp(timestamp) {
    // Format: "00:01:23.456" -> "1m 23s"
    const parts = timestamp.split(':');
    if (parts.length !== 3) return timestamp;

    const hours = parseInt(parts[0], 10);
    const minutes = parseInt(parts[1], 10);
    const seconds = parseFloat(parts[2]);

    let result = '';
    if (hours > 0) {
        result += `${hours}h `;
    }
    if (minutes > 0 || hours > 0) {
        result += `${minutes}m `;
    }
    result += `${Math.round(seconds)}s`;

    return result;
}

// Example event listener that could be used to show fish detail modal
document.addEventListener('DOMContentLoaded', function () {
    // This would be implemented if we added a modal for detailed fish view
    document.body.addEventListener('click', function (e) {
        // Find closest image if clicked on or within a fish row
        const img = e.target.closest('.img-thumbnail');
        if (img) {
            // Could open a modal with larger image and more details
            // showFishDetailModal(img.src, img.closest('tr').dataset.fishId);
        }
    });
}); 